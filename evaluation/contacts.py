"""Conservative contact-request signals; company contact facts are allowed.

These signals complement the quality judge, not a general language classifier.
"""
import re


def asks_for_client_contact(text):
    text=' '.join(text.casefold().split())
    patterns=(
        r'\b(?:как (?:вас зовут|к вам обращаться)|куда (?:вам )?перезвонить)\b',
        r'\b(?:назовите|сообщите|оставьте|укажите|напишите|дайте|продиктуйте|предоставьте)\b[^.!?\n]{0,60}\b(?:имя|телефон|номер|контакт|почту|email|e-mail)\b',
        r'\b(?:можете|могли бы|можно)\b[^.!?\n]{0,40}\b(?:оставить|сообщить|указать|узнать)\b[^.!?\n]{0,40}\b(?:имя|телефон|номер|контакт|почту)\b',
        r'\b(?:какой|как)\b[^.!?\n]{0,20}\b(?:ваш|ваше|ваша)\b[^.!?\n]{0,20}\b(?:имя|телефон|номер|почта|email)\b',
        r'\b(?:ваше имя|ваш (?:номер|телефон|контакт)|ваша почта)\s*\?',
    )
    return any(re.search(pattern,text) for pattern in patterns)
