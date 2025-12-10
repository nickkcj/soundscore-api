import resend
from typing import Optional

from app.config import get_settings

settings = get_settings()


class EmailService:
    """Service for sending emails using Resend."""

    def __init__(self):
        if settings.resend_api_key:
            resend.api_key = settings.resend_api_key

    @staticmethod
    def _get_password_reset_email_html(reset_url: str) -> str:
        """Generate styled HTML email template for password reset."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f9fafb;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #f9fafb;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #C9184A 0%, #831843 100%); padding: 32px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: bold;">SoundScore</h1>
                            <p style="margin: 8px 0 0 0; color: rgba(255, 255, 255, 0.9); font-size: 14px;">Rank your taste in music</p>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px 32px;">
                            <h2 style="margin: 0 0 16px 0; color: #111827; font-size: 24px; font-weight: 600;">Redefinir sua senha</h2>
                            <p style="margin: 0 0 24px 0; color: #6b7280; font-size: 16px; line-height: 1.6;">
                                Recebemos uma solicitacao para redefinir sua senha. Clique no botao abaixo para criar uma nova senha. Este link expira em <strong>15 minutos</strong>.
                            </p>

                            <!-- Button -->
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                <tr>
                                    <td style="text-align: center; padding: 8px 0 24px 0;">
                                        <a href="{reset_url}" style="display: inline-block; padding: 14px 32px; background-color: #C9184A; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 16px; border-radius: 8px;">
                                            Redefinir Senha
                                        </a>
                                    </td>
                                </tr>
                            </table>

                            <p style="margin: 0 0 16px 0; color: #6b7280; font-size: 14px; line-height: 1.6;">
                                Se voce nao solicitou essa redefinicao de senha, pode ignorar este email com seguranca. Sua senha permanecera inalterada.
                            </p>

                            <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                Se o botao nao funcionar, copie e cole este link no seu navegador:<br>
                                <a href="{reset_url}" style="color: #C9184A; word-break: break-all;">{reset_url}</a>
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f9fafb; padding: 24px 32px; text-align: center; border-top: 1px solid #e5e7eb;">
                            <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                Este email foi enviado pelo SoundScore.<br>
                                Se voce tiver alguma duvida, entre em contato com nossa equipe de suporte.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    async def send_password_reset_email(self, to_email: str, reset_token: str) -> bool:
        """
        Send password reset email.

        Args:
            to_email: Recipient email address
            reset_token: The password reset token

        Returns:
            True if email was sent successfully, False otherwise
        """
        reset_url = f"{settings.frontend_url}/reset-password?token={reset_token}"

        if not settings.resend_api_key:
            print(f"[DEV MODE] Password reset link: {reset_url}")
            return True

        html_content = self._get_password_reset_email_html(reset_url)

        try:
            params: resend.Emails.SendParams = {
                "from": "SoundScore <noreply@soundscore.com.br>",
                "to": [to_email],
                "subject": "Redefinir sua senha - SoundScore",
                "html": html_content,
            }
            resend.Emails.send(params)
            return True
        except Exception as e:
            print(f"Failed to send password reset email: {e}")
            return False


email_service = EmailService()
