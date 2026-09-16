"""
poczta.py
Wysyłanie e-maili (powiadomienia o lekcjach, kody resetu hasła) przez SMTP.

Wymaga skonfigurowania danych logowania do skrzynki e-mail w st.secrets:
lokalnie w pliku .streamlit/secrets.toml, a na Streamlit Cloud w panelu
"Settings" -> "Secrets" danej aplikacji. Format (patrz też README):

    [email]
    adres = "twoj_adres@gmail.com"
    haslo_aplikacji = "xxxx xxxx xxxx xxxx"

"haslo_aplikacji" to specjalne "hasło aplikacji" wygenerowane w ustawieniach
konta Google - NIE zwykłe hasło do Gmaila (Google blokuje logowanie zwykłym
hasłem z zewnętrznych programów).
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import streamlit as st


def wyslij_maila(odbiorca, temat, tresc_html):
    """
    Wysyła e-mail HTML na wskazany adres.
    Zwraca (True, None) jeśli się udało, (False, komunikat_bledu) jeśli nie -
    błąd nie przerywa działania aplikacji, tylko jest zwracany do obsłużenia
    przez wywołujący kod (np. pokazania ostrzeżenia w interfejsie).
    """
    try:
        adres_nadawcy = st.secrets["email"]["adres"]
        haslo_aplikacji = st.secrets["email"]["haslo_aplikacji"]
    except (KeyError, FileNotFoundError):
        return False, "Brak konfiguracji SMTP (sekcja [email] w secrets)."

    wiadomosc = MIMEMultipart("alternative")
    wiadomosc["Subject"] = temat
    wiadomosc["From"] = adres_nadawcy
    wiadomosc["To"] = odbiorca
    wiadomosc.attach(MIMEText(tresc_html, "html"))

    try:
        kontekst = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=kontekst) as serwer:
            serwer.login(adres_nadawcy, haslo_aplikacji)
            serwer.sendmail(adres_nadawcy, odbiorca, wiadomosc.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


def _szablon_bazowy(tresc_srodka):
    """Wspólna 'ramka' HTML dla wszystkich maili - nagłówek z logo aplikacji."""
    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f7; padding: 20px; margin: 0;">
        <div style="max-width: 480px; margin: 0 auto; background: white; border-radius: 12px;
                    overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
          <div style="background: #6366f1; padding: 24px; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 22px;">📚 Korepetytor +</h1>
          </div>
          <div style="padding: 24px;">
            {tresc_srodka}
          </div>
        </div>
      </body>
    </html>
    """


def szablon_powiadomienia_o_lekcji(imie_ucznia, data, godzina, czas_trwania):
    """Szablon maila z przypomnieniem o zaplanowanej lekcji."""
    srodek = f"""
        <p style="font-size: 16px; color: #1f2937;">Cześć {imie_ucznia}!</p>
        <p style="font-size: 15px; color: #374151;">Przypominamy o zaplanowanej lekcji:</p>
        <div style="background: #f4f4f7; border-radius: 8px; padding: 16px; margin: 16px 0;">
            <p style="margin: 4px 0; font-size: 15px;"><strong>📅 Data:</strong> {data}</p>
            <p style="margin: 4px 0; font-size: 15px;"><strong>🕒 Godzina:</strong> {godzina}</p>
            <p style="margin: 4px 0; font-size: 15px;"><strong>⏱️ Czas trwania:</strong> {czas_trwania}h</p>
        </div>
        <p style="font-size: 14px; color: #6b7280;">Do zobaczenia!</p>
    """
    return _szablon_bazowy(srodek)


def szablon_powiadomienia_o_serii(imie_ucznia, pierwsza_data, godzina, czas_trwania, liczba_tygodni):
    """Szablon maila informującego o dodaniu cyklicznej serii lekcji (co tydzień)."""
    srodek = f"""
        <p style="font-size: 16px; color: #1f2937;">Cześć {imie_ucznia}!</p>
        <p style="font-size: 15px; color: #374151;">Zaplanowano dla Ciebie cykl lekcji, co tydzień o tej samej porze:</p>
        <div style="background: #f4f4f7; border-radius: 8px; padding: 16px; margin: 16px 0;">
            <p style="margin: 4px 0; font-size: 15px;"><strong>📅 Pierwsza lekcja:</strong> {pierwsza_data}</p>
            <p style="margin: 4px 0; font-size: 15px;"><strong>🕒 Godzina:</strong> {godzina}</p>
            <p style="margin: 4px 0; font-size: 15px;"><strong>⏱️ Czas trwania:</strong> {czas_trwania}h</p>
            <p style="margin: 4px 0; font-size: 15px;"><strong>🔁 Liczba lekcji:</strong> {liczba_tygodni} (co tydzień)</p>
        </div>
        <p style="font-size: 14px; color: #6b7280;">Do zobaczenia na zajęciach!</p>
    """
    return _szablon_bazowy(srodek)


def szablon_kodu_resetu(kod):
    """Szablon maila z kodem do resetu hasła."""
    srodek = f"""
        <p style="font-size: 15px; color: #374151; text-align: center;">Twój kod do resetu hasła:</p>
        <p style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #6366f1; text-align: center;">{kod}</p>
        <p style="font-size: 13px; color: #9ca3af; text-align: center;">Kod jest ważny przez 15 minut.
        Jeśli to nie Ty prosiłeś o reset hasła, zignoruj tę wiadomość.</p>
    """
    return _szablon_bazowy(srodek)
