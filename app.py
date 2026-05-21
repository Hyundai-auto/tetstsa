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

class FastBrowser:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.ready_page = None
        self.lock = asyncio.Lock()

    async def start(self):
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            await self.prepare_next_page()

    async def prepare_next_page(self):
        """Pre-carrega uma aba do checkout em background"""
        context = await self.browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        )
        page = await context.new_page()
        
        # Bloqueio de recursos para carregar mais rápido
        async def block(route):
            if route.request.resource_type in ["image", "font", "media", "stylesheet"]:
                return await route.abort()
            await route.continue_()
        
        await page.route("**/*", block)
        
        try:
            await page.goto(EXTERNAL_CHECKOUT_URL, wait_until='domcontentloaded', timeout=20000)
            # Aguardar o form estar pronto
            await page.wait_for_function("() => window.form !== undefined", timeout=10000)
            self.ready_page = page
            print("Aba de checkout pré-carregada e pronta.")
        except Exception as e:
            print(f"Erro ao pré-carregar: {e}")
            await context.close()

    async def get_ready_page(self):
        async with self.lock:
            page = self.ready_page
            self.ready_page = None
            # Dispara o carregamento da próxima aba em background
            asyncio.create_task(self.prepare_next_page())
            return page

fast_browser = FastBrowser()

@app.before_first_request
def startup():
    # Inicia o browser no primeiro request
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fast_browser.start())

async def generate_pix_instant(payer_name, payer_cpf, payer_phone, payer_email=None):
    if not payer_email:
        safe_name = ''.join(c for c in payer_name.lower() if c.isalpha() or c == ' ').replace(' ', '.')
        payer_email = f"{safe_name}@gmail.com"
    
    cpf_clean = ''.join(c for c in payer_cpf if c.isdigit())
    phone_clean = ''.join(c for c in payer_phone if c.isdigit())
    
    page = await fast_browser.get_ready_page()
    if not page:
        # Fallback se não houver página pronta
        await fast_browser.start()
        page = await fast_browser.get_ready_page()

    pix_url = None
    error_msg = None

    async def handle_response(response):
        nonlocal pix_url, error_msg
        if '/orders' in response.url:
            try:
                data = await response.json()
                if 'redirect' in data and data['redirect']:
                    redirect = data['redirect']
                    pix_url = redirect if redirect.startswith('http') else f"{EXTERNAL_BASE_URL}/{redirect.lstrip('/')}"
                elif 'errors' in data:
                    errors = data['errors']
                    first_error = list(errors.values())[0]
                    error_msg = first_error[0] if isinstance(first_error, list) else str(first_error)
            except: pass

    page.on('response', handle_response)

    try:
        # Injeção instantânea (a página já está aberta!)
        await page.evaluate("""(data) => {
            window.form.email = data.email;
            window.form.first_name = data.name;
            window.form.doc = data.cpf;
            window.form.phone = data.phone;
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
        }""", {'email': payer_email, 'name': payer_name, 'cpf': cpf_clean, 'phone': phone_clean})

        # Aguardar resposta
        for _ in range(40):
            if pix_url or error_msg: break
            if 'obrigado' in page.url:
                pix_url = page.url
                break
            await asyncio.sleep(0.2)
            
    finally:
        # Fecha o contexto da aba usada
        await page.context.close()

    return pix_url, error_msg

@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    data = request.get_json()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        pix_url, error = loop.run_until_complete(generate_pix_instant(
            data.get('payer_name', ''),
            data.get('payer_cpf', ''),
            data.get('payer_phone', ''),
            data.get('payer_email', '')
        ))
    finally:
        loop.close()
    
    if pix_url:
        return jsonify({'success': True, 'pixUrl': pix_url})
    else:
        return jsonify({'success': False, 'error': error or 'Erro ao gerar PIX'})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
