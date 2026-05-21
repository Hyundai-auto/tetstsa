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

# Gerenciador Global do Browser para Alta Performance
class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.lock = asyncio.Lock()

    async def get_browser(self):
        async with self.lock:
            if not self.browser:
                print("Iniciando navegador persistente...")
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
                )
            return self.browser

browser_manager = BrowserManager()

async def generate_pix_high_perf(data):
    payer_name = data.get('payer_name', '')
    payer_cpf = data.get('payer_cpf', '')
    payer_phone = data.get('payer_phone', '')
    payer_email = data.get('payer_email', '')
    
    if not payer_email:
        safe_name = ''.join(c for c in payer_name.lower() if c.isalpha() or c == ' ').replace(' ', '.')
        payer_email = f"{safe_name}@gmail.com"
    
    cpf_clean = ''.join(c for c in payer_cpf if c.isdigit())
    phone_clean = ''.join(c for c in payer_phone if c.isdigit())

    browser = await browser_manager.get_browser()
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    )
    page = await context.new_page()
    
    # Bloqueio de recursos para carregar mais rápido
    await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "font", "media"] else route.continue_())
    
    pix_url = None
    error_msg = None

    async def handle_response(response):
        nonlocal pix_url, error_msg
        if '/orders' in response.url:
            try:
                res_data = await response.json()
                if 'redirect' in res_data:
                    pix_url = res_data['redirect'] if res_data['redirect'].startswith('http') else f"{EXTERNAL_BASE_URL}/{res_data['redirect'].lstrip('/')}"
                elif 'errors' in res_data:
                    error_msg = str(res_data['errors'])
            except: pass

    page.on('response', handle_response)

    try:
        print(f"Iniciando automação para: {payer_name}")
        await page.goto(EXTERNAL_CHECKOUT_URL, wait_until='domcontentloaded', timeout=20000)
        
        # Injeção de dados via JS
        await page.evaluate("""(d) => {
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

        # Aguardar resposta
        for _ in range(60):
            if pix_url or error_msg: break
            if 'obrigado' in page.url:
                pix_url = page.url
                break
            await asyncio.sleep(0.2)
            
    except Exception as e:
        error_msg = str(e)
    finally:
        await context.close()

    return pix_url, error_msg

@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    data = request.get_json()
    try:
        # Criar um novo loop para cada request para evitar conflitos no Flask
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        pix_url, error = loop.run_until_complete(generate_pix_high_perf(data))
        loop.close()
        
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
    app.run(host='0.0.0.0', port=port, threaded=True)
