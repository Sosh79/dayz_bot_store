# -*- coding: utf-8 -*-
import sys
import subprocess
import os
import logging
import traceback

# Configuração inicial de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Função para instalar dependências automaticamente
def install_dependencies():
    required = ['discord.py', 'python-dotenv', 'mercadopago', 'qrcode', 'pillow', 'aiohttp', 'validators', 'pymongo', 'motor', 'paypalrestsdk', 'paramiko']
    installed = False
    
    logger.info("Verificando e instalando dependências necessárias...")
    
    for package in required:
        try:
            __import__(package.replace('-', '_').split('.')[0])
            logger.info(f"✓ {package} já instalado")
        except ImportError:
            logger.info(f"Instalando {package}...")
            try:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', package, '--quiet'])
                installed = True
                logger.info(f"✓ {package} instalado com sucesso")
            except Exception as e:
                logger.error(f"Erro ao instalar {package}: {str(e)}")
                print(f"Erro ao instalar {package}. O bot pode não funcionar corretamente.")
    
    if installed:
        logger.info("Todas as dependências foram instaladas. Por favor, reinicie o bot manualmente.")
        print("Dependências instaladas. Por favor, reinicie o bot manualmente.")
        sys.exit(0)  # Sair com código 0 (sucesso) para que o usuário reinicie manualmente

# Instalar dependências antes de qualquer outra importação
install_dependencies()
