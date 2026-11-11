import os
import smtplib
from email.message import EmailMessage


def send_application_email(interaction, config):
    from providers.local_settings import local_only
    if local_only(): return False
    recipient = config.get("notification_email", "").strip() or os.getenv("BUSINESS_EMAIL", "").strip()
    host = os.getenv("SMTP_HOST", "").strip()
    if not recipient or not host:
        return False
    message = EmailMessage()
    message["Subject"] = f"Новое обращение — {config['business_name']}"
    message["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or config["business_name"]
    message["To"] = recipient
    labels = {f["id"]: f["label"] for f in interaction.get("agent_config", {}).get("fields", [])}
    labels.update({q["id"]: q["label"] for q in config.get("custom_questions", [])})
    details = "\n".join(f"{labels.get(key, key)}: {value}" for key, value in (interaction.get("action_result") or interaction.get("structured_data", {})).items())
    message.set_content(f"Обращение в {config['business_name']}\n\n"
                        f"Имя: {interaction.get('customer_name') or '—'}\nТелефон: {interaction.get('phone') or '—'}\n"
                        f"Намерение: {interaction.get('intent') or '—'}\nРезультат: {interaction.get('result') or 'Разговор остановлен'}\n"
                        f"{details}\n\nКонтекст:\n{interaction.get('summary', '')}\n\nТестовый календарь. Реального телефонного перевода нет.")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.starttls()
        smtp.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return True
