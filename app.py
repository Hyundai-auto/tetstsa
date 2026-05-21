import os
import re
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from curl_cffi import requests

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

EXTERNAL_CHECKOUT_URL = "https://pay.meuservicomei.com.br/r/a51L1PhTl58c6S86"
EXTERNAL_BASE_URL = "https://pay.meuservicomei.com.br"

def get_pix_ultra_fast(payer_name, payer_cpf, payer_phone, payer_email=None):
    """
    Gera o PIX usando curl_cffi para simular um navegador real (impersonate chrome).
    Isso é extremamente rápido e leve, ideal para o Render.
    """
    if not payer_email:
        safe_name = ''.join(c for c in payer_name.lower() if c.isalpha() or c == ' ').replace(' ', '.')
        payer_email = f"{safe_name}@gmail.com"
    
    cpf_clean = ''.join(c for c in payer_cpf if c.isdigit())
    phone_clean = ''.join(c for c in payer_phone if c.isdigit())

    try:
        # Criar uma sessão que simula perfeitamente o Chrome
        with requests.Session(impersonate="chrome110") as s:
            # 1. Acessar a página para pegar cookies e tokens
            resp = s.get(EXTERNAL_CHECKOUT_URL, timeout=15)
            html = resp.text
            
            # Extrair CSRF Token
            csrf_match = re.search(r'name="_token"[^>]+value="([^"]+)"', html)
            if not csrf_match:
                csrf_match = re.search(r'value="([^"]+)"[^>]+name="_token"', html)
            csrf_token = csrf_match.group(1) if csrf_match else None
            
            # Extrair Cart Token
            cart_match = re.search(r"cart_token['\": ]+['\"]([a-f0-9\-]{36})['\"]", html)
            cart_token = cart_match.group(1) if cart_match else None
            
            if not csrf_token or not cart_token:
                return None, "Não foi possível obter os tokens de segurança do checkout externo."

            # 2. Enviar o pedido via POST
            payload = {
                "cart_token": cart_token,
                "payment_method": "pix_appmax",
                "email": payer_email,
                "first_name": payer_name,
                "doc": cpf_clean,
                "phone": phone_clean,
                "postal_code": "01310-100",
                "address_line_1": "Avenida Paulista",
                "address_number": "1000",
                "address_neighborhood": "Bela Vista",
                "city": "São Paulo",
                "state": "SP",
                "address_disabled": 1,
                "opt_in": True
            }
            
            order_headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRF-TOKEN': csrf_token,
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': EXTERNAL_BASE_URL,
                'Referer': resp.url,
            }
            
            order_resp = s.post(f"{EXTERNAL_BASE_URL}/orders", headers=order_headers, json=payload, timeout=20)
            order_data = order_resp.json()
            
            if 'redirect' in order_data:
                redirect = order_data['redirect']
                pix_url = redirect if redirect.startswith('http') else f"{EXTERNAL_BASE_URL}/{redirect.lstrip('/')}"
                return pix_url, None
            elif 'errors' in order_data:
                errors = order_data['errors']
                first_error = list(errors.values())[0]
                return None, first_error[0] if isinstance(first_error, list) else str(first_error)
            else:
                return None, "O servidor de pagamento retornou uma resposta inesperada."

    except Exception as e:
        return None, f"Erro de conexão: {str(e)}"

@app.route('/proxy/pix', methods=['POST'])
def proxy_pix():
    data = request.get_json()
    pix_url, error = get_pix_ultra_fast(
        data.get('payer_name', ''),
        data.get('payer_cpf', ''),
        data.get('payer_phone', ''),
        data.get('payer_email', '')
    )
    
    if pix_url:
        return jsonify({'success': True, 'pixUrl': pix_url})
    else:
        return jsonify({'success': False, 'error': error})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
