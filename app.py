import os
import asyncio
import json
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from playwright.async_api import async_playwright

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

EXTERNAL_CHECKOUT_URL = "https://pay.meuservicomei.com.br/r/a51L1PhTl58c6S86"
EXTERNAL_BASE_URL = "https://pay.meuservicomei.com.br"

# OTIMIZAÇÃO: Usar uma função simples e robusta para cada request
# Para evitar erros 500 de loop, vamos criar uma sessão limpa por pedido,
# mas com bloqueio total de recursos para ser ultra-rápido.

async def run_automation(data):
    payer_name = data.get('payer_name', '')
    payer_cpf = data.get('payer_cpf', '')
    payer_phone = data.get('payer_phone', '')
    payer_email = data.get('payer_email', '')
    
    if not payer_email:
        safe_name = ''.join(c for c in payer_name.lower() if c.isalpha() or c == ' ').replace(' ', '.')
        payer_email = f"{safe_name}@gmail.com"
    
    cpf_clean = ''.join(c for c in payer_cpf if c.isdigit())
    phone_clean = ''.join(c for c in payer_phone if c.isdigit())

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        )
        page = await context.new_page()
        
        # Bloqueio total de recursos pesados
        async def block(route):
            if route.request.resource_type in ["image", "font", "media", "stylesheet"]:
                return await route.abort()
            await route.continue_()
        
        await page.route("**/*", block)
        
        pix_url = None
        error_msg = None

        async def handle_response(response):
            nonlocal pix_url, error_msg
            if '/orders' in response.url:
                try:
                    res_data = await response.json()
                    if 'redirect' in res_data and res_data['redirect']:
                        redirect = res_data['redirect']
                        pix_url = redirect if redirect.startswith('http') else f"{EXTERNAL_BASE_URL}/{redirect.lstrip('/')}"
                    elif 'errors' in res_data:
                        errors = res_data['errors']
                        first_error = list(errors.values())[0]
                        error_msg = first_error[0] if isinstance(first_error, list) else str(first_error)
                except: pass

        page.on('response', handle_response)

        try:
            # Navegação rápida
            await page.goto(EXTERNAL_CHECKOUT_URL, wait_until='domcontentloaded', timeout=15000)
            
            # Injeção de dados
            await page.evaluate("""(d) => {
                const check = setInterval(() => {
                    if (window.form && typeof realizarPagamento === 'function') {
                        clearInterval(check);
                        window.form.email = d.email;
                        window.form.first_name = d.name;
                        window.form.doc = d.cpf;
                        window.form.phone = d.phone;
                        window.form.postal_code = '01310-100';
                        window.form.address_line_1 = 'Avenida Paulista';
                        window.form.address_number = '1000';
                        window.form.address_neighborhood = 'Bela Vista';
                        window.form.city = 'São Paulo';
                        window.form.state = 'SP';
                        window.form.inputs_with_errors = [];
                        window.form.address_disabled = 1;
                        window.form.payment_method = 'pix_appmax';
                        
                        const btn = document.querySelector('#general-submit-button');
                        if (btn) {
                            btn.disabled = false;
                            realizarPagamento(btn);
                        }
                    }
                }, 100);
            }""", {'email': payer_email, 'name': payer_name, 'cpf': cpf_clean, 'phone': phone_clean})

            # Aguardar resposta
            for _ in range(50):
                if pix_url or error_msg: break
                if 'obrigado' in page.url:
                    pix_url = page.url
                    break
                await asyncio.sleep(0.2)
                
        except Exception as e:
            error_msg = str(e)
        finally:
            await browser.close()

        return pix_url, error_msg

@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    data = request.get_json()
    
    # Executar automação de forma isolada para evitar erro 500
    try:
        pix_url, error = asyncio.run(run_automation(data))
        if pix_url:
            return jsonify({'success': True, 'pixUrl': pix_url})
        else:
            return jsonify({'success': False, 'error': error or 'Erro ao gerar PIX'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
