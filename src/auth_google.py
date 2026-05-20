"""Setup do OAuth do Google. Roda 1x no setup inicial.

Uso:
    python -m src.auth_google

Pré-requisitos:
    1. Criar projeto no Google Cloud Console
    2. Habilitar Google Calendar API
    3. Criar OAuth client (tipo Desktop)
    4. Baixar JSON e salvar em credentials/google_oauth.json

O script abre o navegador, você autoriza, e gera credentials/token.json.
Pode rodar de novo a qualquer momento: se já autorizado, só confirma; se
expirado, renova; se faltando, faz o flow completo.
"""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src import config


def authorize() -> Credentials:
    creds: Credentials | None = None

    if config.GOOGLE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(
            str(config.GOOGLE_TOKEN_PATH), config.GOOGLE_CALENDAR_SCOPES
        )

    if creds and creds.valid:
        print("✅ Token existente e válido. Nada a fazer.")
        return creds

    if creds and creds.expired and creds.refresh_token:
        print("🔄 Token expirado, renovando via refresh_token...")
        creds.refresh(Request())
    else:
        if not config.GOOGLE_OAUTH_CLIENT_PATH.exists():
            raise FileNotFoundError(
                f"Credenciais OAuth não encontradas em {config.GOOGLE_OAUTH_CLIENT_PATH}. "
                f"Baixe o JSON do OAuth client no Google Cloud Console e salve nesse caminho."
            )
        print("🌐 Abrindo navegador para autorização...")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.GOOGLE_OAUTH_CLIENT_PATH), config.GOOGLE_CALENDAR_SCOPES
        )
        creds = flow.run_local_server(port=0)

    config.GOOGLE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"✅ Token salvo em {config.GOOGLE_TOKEN_PATH}")
    return creds


if __name__ == "__main__":
    authorize()
