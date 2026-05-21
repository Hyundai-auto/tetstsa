import os
import time
import json
import re
import sys
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from playwright.sync_api import sync_playwright

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

EXTERNAL_CHECKOUT_URL = "https://pay.meuservicomei.com.br/r/a51L1PhTl58c6S86"
EXTERNAL_BASE_URL = "https://pay.meuservicomei.com.br"

def log_debug(msg):
    print(f"[DEBUG] {msg}", file=sys.stderr)

def generate_pix_logic(data):
    payer_name = data.get('payer_name', '')
    payer_cpf = data.get('payer_cpf', '')
    payer_phone = data.get('payer_phone', '')
    payer_email = data.get('payer_email', '')
    
    if not payer_email:
        safe_name = ''.join(c for c in payer_name.lower() if c.isalpha() or c == ' ').replace(' ', '.')
        payer_email = f"{safe_name}@gmail.com"
    
    cpf_clean = ''.join(c for c in payer_cpf if c.isdigit())
    phone_clean = ''.join(c for c in payer_phone if c.isdigit())

    log_debug(f"Iniciando processo para: {payer_name} | CPF: {cpf_clean}")

    with sync_playwright() as p:
        try:
            log_debug("Lançando navegador Chromium...")
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            )
            page = context.new_page()
            
            # Bloqueio de recursos pesados
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "font", "media"] else route.continue_())
            
            pix_url = None
            error_msg = None

            def handle_response(response):
                nonlocal pix_url, error_msg
                if '/orders' in response.url:
                    try:
                        res_data = response.json()
                        log_debug(f"Resposta da API /orders recebida: {res_data}")
                        if 'redirect' in res_data:
                            redirect = res_data['redirect']
                            pix_url = redirect if redirect.startswith('http') else f"{EXTERNAL_BASE_URL}/{redirect.lstrip('/')}"
                        elif 'errors' in res_data:
                            error_msg = str(res_data['errors'])
                    except Exception as e:
                        log_debug(f"Erro ao processar JSON da resposta: {e}")

            page.on('response', handle_response)

            log_debug(f"Navegando para: {EXTERNAL_CHECKOUT_URL}")
            page.goto(EXTERNAL_CHECKOUT_URL, wait_until='domcontentloaded', timeout=30000)
            
            log_debug("Injetando dados no formulário via JavaScript...")
            page.evaluate("""(d) => {
                const i = setInterval(() => {
                    if (window.form && typeof realizarPagamento === 'function') {
                        clearInterval(i);
                        Object.assign(window.form, {
                            email: d.email, first_name: d.name, doc: d.cpf, phone: d.phone,
                            postal_code: '01310-100', address_line_1: 'Avenida Paulista',
                            address_number: '1000', address_neighborhood: 'Bela Vista',
                            city: 'São Paulo', state: 'SP', inputs_with_errors: [],
                            address_disabled: 1, payment_method: 'pix_appmax'
                        });
                        const b = document.querySelector('#general-submit-button');
                        if (b) { b.disabled = false; realizarPagamento(b); }
                    }
                }, 100);
            }""", {'email': payer_email, 'name': payer_name, 'cpf': cpf_clean, 'phone': phone_clean})

            log_debug("Aguardando geração do PIX (polling)...")
            start_time = time.time()
            while time.time() - start_time < 25:
                if pix_url:
                    log_debug(f"Sucesso! PIX gerado: {pix_url}")
                    break
                if error_msg:
                    log_debug(f"Erro retornado pelo checkout: {error_msg}")
                    break
                if 'obrigado' in page.url:
                    pix_url = page.url
                    log_debug(f"Redirecionamento detectado pela URL: {pix_url}")
                    break
                time.sleep(0.5)
            
            browser.close()
            return pix_url, error_msg
        except Exception as e:
            log_debug(f"Exceção durante a automação: {e}")
            return None, str(e)

@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    data = request.get_json()
    try:
        pix_url, error = generate_pix_logic(data)
        if pix_url:
            return jsonify({'success': True, 'pixUrl': pix_url})
        else:
            return jsonify({'success': False, 'error': error or 'O checkout externo demorou muito para responder. Tente novamente.'})
    except Exception as e:
        log_debug(f"Erro Crítico no Servidor: {e}")
        return jsonify({'success': False, 'error': 'Erro interno no servidor. Verifique os logs.'}), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
