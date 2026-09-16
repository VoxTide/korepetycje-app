"""
app.py
Interfejs Streamlit dla systemu rezerwacji korepetycji, z kontami użytkowników.

Uruchomienie lokalne:
    streamlit run app.py
"""

import streamlit as st
from datetime import date, time, timedelta
import database as db
import re
from streamlit_calendar import calendar
import poczta

db.init_db()


def czy_poprawny_telefon(telefon):
    """
    Sprawdza, czy numer telefonu wygląda poprawnie.
    Akceptuje puste pole (telefon jest opcjonalny), 9 cyfr, opcjonalnie z prefiksem +48.
    Ignoruje spacje i myślniki w numerze.
    """
    if not telefon.strip():
        return True  # pole opcjonalne - puste jest ok

    oczyszczony = re.sub(r"[\s-]", "", telefon)
    return bool(re.fullmatch(r"(\+48)?\d{9}", oczyszczony))


def zapamietaj_komunikat(typ, tresc):
    """
    Dodaje komunikat (np. 'Lekcja dodana!') do kolejki w session_state, żeby
    przetrwał st.rerun(). Bez tego st.success() wywołane tuż przed st.rerun()
    znika z ekranu w ułamku sekundy, bo strona natychmiast się przeładowuje.
    Może być więcej niż jeden komunikat naraz (np. sukces + ostrzeżenie o mailu).
    """
    st.session_state.setdefault("zapamietane_komunikaty", []).append((typ, tresc))


def pokaz_zapamietany_komunikat():
    """Wyświetla komunikaty zapisane przed ostatnim st.rerun() (jeśli są) i czyści je."""
    for typ, tresc in st.session_state.pop("zapamietane_komunikaty", []):
        if typ == "success":
            st.success(tresc)
        elif typ == "warning":
            st.warning(tresc)
        elif typ == "error":
            st.error(tresc)


ETYKIETY_STATUSOW_LEKCJI = {
    "zaplanowana": "🕒 Zaplanowana",
    "odbyta": "✅ Odbyta",
    "odwolana": "❌ Odwołana",
}


def pokaz_kontrolki_lekcji(lekcja, korepetytor_id, klucz_prefix):
    """
    Wspólny widżet do ręcznej zmiany statusu lekcji i jej trwałego usunięcia.
    Używany w Dashboardzie, Kalendarzu i Historii ucznia, żeby zachowanie
    i wygląd były wszędzie takie same.
    """
    opcje_statusow = list(ETYKIETY_STATUSOW_LEKCJI.keys())
    indeks_obecnego = opcje_statusow.index(lekcja["status"])

    col_status, col_zastosuj = st.columns([2, 1])
    with col_status:
        wybrany_status = st.selectbox(
            "Status",
            opcje_statusow,
            index=indeks_obecnego,
            format_func=lambda s: ETYKIETY_STATUSOW_LEKCJI[s],
            key=f"{klucz_prefix}_status_{lekcja['id']}",
            label_visibility="collapsed",
        )
    with col_zastosuj:
        if st.button("Zastosuj", key=f"{klucz_prefix}_zastosuj_{lekcja['id']}"):
            if wybrany_status != lekcja["status"]:
                db.change_lesson_status_manual(lekcja["id"], korepetytor_id, wybrany_status)
                zapamietaj_komunikat("success", "Status lekcji zaktualizowany.")
                st.rerun()

    if st.session_state.get(f"{klucz_prefix}_potwierdz_usun_{lekcja['id']}", False):
        st.warning("Usunięcie jest nieodwracalne - lekcja zniknie całkowicie, bez śladu w historii.")
        col_tak, col_nie = st.columns(2)
        with col_tak:
            if st.button("Tak, usuń na stałe", key=f"{klucz_prefix}_usun_tak_{lekcja['id']}"):
                db.delete_lesson(lekcja["id"], korepetytor_id)
                st.session_state[f"{klucz_prefix}_potwierdz_usun_{lekcja['id']}"] = False
                zapamietaj_komunikat("success", "Lekcja usunięta na stałe.")
                st.rerun()
        with col_nie:
            if st.button("Anuluj", key=f"{klucz_prefix}_usun_nie_{lekcja['id']}"):
                st.session_state[f"{klucz_prefix}_potwierdz_usun_{lekcja['id']}"] = False
                st.rerun()
    else:
        if st.button("🗑️ Usuń na stałe", key=f"{klucz_prefix}_usun_{lekcja['id']}"):
            st.session_state[f"{klucz_prefix}_potwierdz_usun_{lekcja['id']}"] = True
            st.rerun()


st.set_page_config(page_title="Korepetytor +", page_icon="📚", layout="wide")

# Własny CSS - ciemny, nowoczesny wygląd paska bocznego z zaokrąglonymi
# pozycjami menu (Streamlit nie ma wbudowanej opcji do tego, więc modyfikujemy
# wygląd bezpośrednio przez CSS, celując w wewnętrzne elementy widgetów)
st.markdown("""
    <style>
    /* Ciemne tło całego paska bocznego */
    section[data-testid="stSidebar"] {
        background-color: #1e1b3a;
    }
    section[data-testid="stSidebar"] * {
        color: #e5e7eb !important;
    }

    /* Nazwa aplikacji na górze paska bocznego */
    .sidebar-app-title {
        font-size: 1.9rem;
        font-weight: 800;
        color: #ffffff !important;
        padding: 0.5rem 0 1.8rem 0;
    }

    /* Pozycje menu jako zaokrąglone "kafelki" zamiast zwykłych radio buttonów */
    div[data-testid="stSidebar"] div[role="radiogroup"] {
        gap: 0.3rem;
    }
    div[data-testid="stSidebar"] div[role="radiogroup"] label {
        display: flex;
        align-items: center;
        font-size: 1.1rem;
        padding: 0.7rem 1rem;
        margin-bottom: 0.2rem;
        border-radius: 12px;
        transition: background-color 0.15s ease;
        cursor: pointer;
    }
    div[data-testid="stSidebar"] div[role="radiogroup"] label p {
        font-size: 1.1rem;
    }
    div[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
        background-color: rgba(255, 255, 255, 0.08);
    }
    /* Podświetlenie aktywnie wybranej pozycji menu */
    div[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
        background-color: #6366f1;
    }
    /* Ukrycie domyślnego kółka radio-button - zostaje sama ikona + tekst */
    div[data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child {
        display: none;
    }
    </style>
""", unsafe_allow_html=True)


# --- EKRAN LOGOWANIA / REJESTRACJI ---
# Pokazuje się zawsze, gdy nikt nie jest zalogowany (sprawdzamy przez session_state)

def pokaz_ekran_logowania():
    tab_logowanie, tab_rejestracja, tab_reset = st.tabs(["Zaloguj się", "Załóż konto", "Zapomniałem hasła"])

    with tab_logowanie:
        login = st.text_input("Login", key="login_logowanie")
        haslo = st.text_input("Hasło", type="password", key="haslo_logowanie")

        if st.button("Zaloguj się"):
            if not login or not haslo:
                st.error("Podaj login i hasło.")
            else:
                user_id = db.verify_user(login, haslo)
                if user_id is None:
                    st.error("Nieprawidłowy login lub hasło.")
                else:
                    st.session_state["user_id"] = user_id
                    st.session_state["login"] = login
                    st.rerun()

    with tab_rejestracja:
        nowy_login = st.text_input("Wybierz login", key="login_rejestracja")
        nowy_email = st.text_input("Adres e-mail (potrzebny do resetu hasła)", key="email_rejestracja")
        nowe_haslo = st.text_input("Wybierz hasło", type="password", key="haslo_rejestracja")
        powtorz_haslo = st.text_input("Powtórz hasło", type="password", key="haslo_rejestracja_2")

        if st.button("Załóż konto"):
            if not nowy_login or not nowe_haslo or not nowy_email.strip():
                st.error("Wypełnij wszystkie pola, łącznie z adresem e-mail.")
            elif nowe_haslo != powtorz_haslo:
                st.error("Hasła nie są identyczne.")
            elif len(nowe_haslo) < 4:
                st.error("Hasło musi mieć co najmniej 4 znaki.")
            else:
                try:
                    db.create_user(nowy_login, nowe_haslo, nowy_email.strip())
                    st.success("Konto utworzone! Możesz się teraz zalogować w zakładce obok.")
                except ValueError as e:
                    st.error(str(e))

    with tab_reset:
        st.caption("Podaj swój login, na Twój adres e-mail wyślemy kod, którym ustawisz nowe hasło.")

        # Etap 1: podanie loginu i wysłanie kodu na e-mail
        login_reset = st.text_input("Login", key="login_reset")

        if st.button("Wyślij kod na e-mail", key="reset_krok1"):
            email_konta = db.get_user_email(login_reset)
            if email_konta is None:
                st.error("Nie znaleziono konta o takim loginie.")
            elif not email_konta:
                st.error("To konto nie ma przypisanego adresu e-mail - reset nie jest możliwy. Załóż nowe konto.")
            else:
                kod = db.wygeneruj_kod_resetu(login_reset)
                udalo_sie, blad = poczta.wyslij_maila(
                    email_konta,
                    "Kod resetu hasła - Korepetytor +",
                    poczta.szablon_kodu_resetu(kod)
                )
                if udalo_sie:
                    st.session_state["reset_login"] = login_reset
                    st.success(f"Wysłano kod na adres {email_konta}. Sprawdź skrzynkę (także spam).")
                else:
                    st.error(f"Nie udało się wysłać e-maila: {blad}")

        # Etap 2: podanie kodu i nowego hasła
        if st.session_state.get("reset_login"):
            st.divider()
            kod_wpisany = st.text_input("Kod z e-maila", key="kod_reset")
            nowe_haslo_reset = st.text_input("Nowe hasło", type="password", key="nowe_haslo_reset")
            powtorz_haslo_reset = st.text_input("Powtórz nowe hasło", type="password", key="powtorz_haslo_reset")

            if st.button("Zresetuj hasło", key="reset_krok2"):
                if not db.zweryfikuj_kod_resetu(st.session_state["reset_login"], kod_wpisany):
                    st.error("Niepoprawny lub wygasły kod. Poproś o nowy kod powyżej.")
                elif nowe_haslo_reset != powtorz_haslo_reset:
                    st.error("Hasła nie są identyczne.")
                elif len(nowe_haslo_reset) < 4:
                    st.error("Hasło musi mieć co najmniej 4 znaki.")
                else:
                    db.reset_password(st.session_state["reset_login"], nowe_haslo_reset)
                    db.wyczysc_kod_resetu(st.session_state["reset_login"])
                    st.success("Hasło zostało zmienione! Możesz się teraz zalogować w zakładce obok.")
                    del st.session_state["reset_login"]


def pokaz_ekran_logowania_ucznia():
    tab_logowanie, tab_rejestracja = st.tabs(["Zaloguj się", "Załóż konto"])

    with tab_logowanie:
        login = st.text_input("Login", key="login_uczen")
        haslo = st.text_input("Hasło", type="password", key="haslo_uczen")

        if st.button("Zaloguj się", key="zaloguj_uczen"):
            if not login or not haslo:
                st.error("Podaj login i hasło.")
            else:
                uczen_id = db.verify_student(login, haslo)
                if uczen_id is None:
                    st.error("Nieprawidłowy login lub hasło.")
                else:
                    st.session_state["uczen_konto_id"] = uczen_id
                    st.session_state["uczen_login"] = login
                    st.rerun()

    with tab_rejestracja:
        st.caption(
            "Aby założyć konto, potrzebujesz kodu zaproszenia od swojego korepetytora "
            "(znajduje się w widoku „Lista uczniów” w jego aplikacji)."
        )
        kod = st.text_input("Kod zaproszenia", key="kod_zaproszenia_rejestracja")
        nowy_login = st.text_input("Wybierz login", key="login_rejestracja_uczen")
        nowe_haslo = st.text_input("Wybierz hasło", type="password", key="haslo_rejestracja_uczen")
        powtorz_haslo = st.text_input("Powtórz hasło", type="password", key="haslo_rejestracja_uczen_2")

        if st.button("Załóż konto", key="zaloz_konto_uczen"):
            if not kod.strip() or not nowy_login or not nowe_haslo:
                st.error("Wypełnij wszystkie pola.")
            elif nowe_haslo != powtorz_haslo:
                st.error("Hasła nie są identyczne.")
            elif len(nowe_haslo) < 4:
                st.error("Hasło musi mieć co najmniej 4 znaki.")
            else:
                try:
                    db.stworz_konto_ucznia(kod, nowy_login, nowe_haslo)
                    st.success("Konto utworzone! Możesz się teraz zalogować w zakładce obok.")
                except ValueError as e:
                    st.error(str(e))


def pokaz_widok_ucznia():
    """Uproszczony, wyłącznie do odczytu widok dla zalogowanego ucznia - jego własne dane i lekcje."""
    uczen_id = st.session_state["uczen_konto_id"]
    profil = db.get_student_own_profile(uczen_id)

    if profil is None:
        st.error("Nie znaleziono Twojego profilu - skontaktuj się z korepetytorem.")
        if st.button("Wyloguj się"):
            del st.session_state["uczen_konto_id"]
            del st.session_state["uczen_login"]
            st.rerun()
        return

    st.sidebar.markdown('<div class="sidebar-app-title">📚 Korepetytor +</div>', unsafe_allow_html=True)
    with st.sidebar.expander(f"🎓 {profil['imie']}"):
        if st.button("Wyloguj się", key="wyloguj_uczen"):
            del st.session_state["uczen_konto_id"]
            del st.session_state["uczen_login"]
            st.rerun()

    st.title(f"Cześć, {profil['imie']}! 👋")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Pozostałe godziny w pakiecie", f"{profil['pakiet_godzin']}h")

    lekcje_nadchodzace = db.get_own_upcoming_lessons(uczen_id)

    st.subheader("Nadchodzące lekcje")
    if not lekcje_nadchodzace:
        st.caption("Brak zaplanowanych lekcji.")
    else:
        for lekcja in lekcje_nadchodzace:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"🕒 **{lekcja['data']} o {lekcja['godzina']}** ({lekcja['czas_trwania']}h)")
                if lekcja["notatka"]:
                    st.caption(f"Notatka: {lekcja['notatka']}")
            with col2:
                if st.button("Odwołaj", key=f"uczen_odwolaj_{lekcja['id']}"):
                    try:
                        db.cancel_lesson_by_student(lekcja["id"], uczen_id)
                        st.success("Lekcja odwołana.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    st.divider()

    with st.expander("📜 Historia lekcji"):
        historia = db.get_own_lesson_history(uczen_id)
        if not historia:
            st.caption("Brak lekcji w historii.")
        else:
            etykiety_statusow = {
                "zaplanowana": "🕒 Zaplanowana",
                "odbyta": "✅ Odbyta",
                "odwolana": "❌ Odwołana"
            }
            for lekcja in historia:
                etykieta = etykiety_statusow.get(lekcja["status"], lekcja["status"])
                st.caption(f"{lekcja['data']} {lekcja['godzina']} ({lekcja['czas_trwania']}h) — {etykieta}")


# --- SPRAWDZENIE, CZY UŻYTKOWNIK JEST ZALOGOWANY ---

if "user_id" not in st.session_state and "uczen_konto_id" not in st.session_state:
    st.title("📚 Korepetytor +")
    rola = st.radio("Kim jesteś?", ["Korepetytor", "Uczeń"], horizontal=True, label_visibility="collapsed")
    st.divider()
    if rola == "Korepetytor":
        pokaz_ekran_logowania()
    else:
        pokaz_ekran_logowania_ucznia()
    st.stop()  # zatrzymuje wykonywanie reszty skryptu, dopóki ktoś się nie zaloguje

if "uczen_konto_id" in st.session_state:
    pokaz_widok_ucznia()
    st.stop()  # widok ucznia jest całkowicie osobny - reszta pliku (aplikacja korepetytora) go nie dotyczy

# Od tego miejsca w dół — zalogowany jest korepetytor
korepetytor_id = st.session_state["user_id"]

# --- PASEK BOCZNY ---
st.sidebar.markdown('<div class="sidebar-app-title">📚 Korepetytor +</div>', unsafe_allow_html=True)

with st.sidebar.expander(f"👤 {st.session_state['login']}"):
    # Usuwanie konta - z dwuetapowym potwierdzeniem, tak jak przy usuwaniu ucznia
    if st.session_state.get("potwierdz_usun_konto", False):
        st.warning("Usunięcie konta jest nieodwracalne — stracisz wszystkich uczniów i lekcje.")
        col_tak, col_nie = st.columns(2)
        with col_tak:
            if st.button("Tak, usuń", key="usun_konto_tak"):
                db.delete_user(korepetytor_id)
                del st.session_state["user_id"]
                del st.session_state["login"]
                del st.session_state["potwierdz_usun_konto"]
                st.rerun()
        with col_nie:
            if st.button("Anuluj", key="usun_konto_nie"):
                st.session_state["potwierdz_usun_konto"] = False
                st.rerun()
    else:
        if st.button("🗑️ Usuń konto"):
            st.session_state["potwierdz_usun_konto"] = True
            st.rerun()

    st.divider()

    if st.button("Wyloguj się"):
        del st.session_state["user_id"]
        del st.session_state["login"]
        st.rerun()

st.sidebar.markdown("<br>", unsafe_allow_html=True)

menu = st.sidebar.radio(
    "Menu",
    ["📊 Podsumowanie", "📅 Kalendarz", "➕ Dodaj lekcję", "🎓 Lista uczniów"],
    label_visibility="collapsed"
)
# Usuwamy prefiksy z ikonami przy porównaniach niżej, żeby nie trzeba było
# zmieniać całej reszty kodu odwołującej się do nazw bez ikon
menu = menu.split(" ", 1)[1]

# --- WIDOK: PODSUMOWANIE (DASHBOARD) ---
if menu == "Podsumowanie":
    st.header("📊 Podsumowanie")
    pokaz_zapamietany_komunikat()

    uczniowie = db.get_students(korepetytor_id)
    dzis = date.today()
    jutro = dzis + timedelta(days=1)

    lekcje_dzis = db.get_lessons_by_date_range(korepetytor_id, dzis.isoformat(), dzis.isoformat())
    lekcje_dzis = [l for l in lekcje_dzis if l["status"] == "zaplanowana"]

    lekcje_jutro = db.get_lessons_by_date_range(korepetytor_id, jutro.isoformat(), jutro.isoformat())
    lekcje_jutro = [l for l in lekcje_jutro if l["status"] == "zaplanowana"]

    uczniowie_malo_godzin = [u for u in uczniowie if u["pakiet_godzin"] <= 1]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Lekcje dzisiaj", len(lekcje_dzis))
    with col2:
        st.metric("Lekcje jutro", len(lekcje_jutro))
    with col3:
        st.metric("Liczba uczniów", len(uczniowie))

    st.divider()

    col_dzis, col_jutro = st.columns(2)

    with col_dzis:
        st.subheader("Dziś")
        if not lekcje_dzis:
            st.caption("Brak lekcji na dziś.")
        else:
            for lekcja in sorted(lekcje_dzis, key=lambda l: l["godzina"]):
                st.write(f"🕒 {lekcja['godzina']} — {lekcja['imie']} {lekcja['nazwisko'] or ''}")
                pokaz_kontrolki_lekcji(lekcja, korepetytor_id, "dash_dzis")
                st.divider()

    with col_jutro:
        st.subheader("Jutro")
        if not lekcje_jutro:
            st.caption("Brak lekcji na jutro.")
        else:
            for lekcja in sorted(lekcje_jutro, key=lambda l: l["godzina"]):
                st.write(f"🕒 {lekcja['godzina']} — {lekcja['imie']} {lekcja['nazwisko'] or ''}")
                pokaz_kontrolki_lekcji(lekcja, korepetytor_id, "dash_jutro")
                st.divider()

    st.divider()

    st.subheader("⚠️ Uczniowie z kończącym się pakietem")
    if not uczniowie_malo_godzin:
        st.caption("Nikomu nie kończą się godziny — wszystko w porządku.")
    else:
        for u in sorted(uczniowie_malo_godzin, key=lambda u: u["pakiet_godzin"]):
            st.error(f"{u['imie']} {u['nazwisko'] or ''} — zostało {u['pakiet_godzin']}h")

    st.divider()

    with st.expander("📈 Raport miesięczny"):
        nazwy_miesiecy = [
            "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
            "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"
        ]

        col_miesiac, col_rok = st.columns(2)
        with col_miesiac:
            wybrany_miesiac = st.selectbox("Miesiąc", nazwy_miesiecy, index=dzis.month - 1)
        with col_rok:
            wybrany_rok = st.selectbox("Rok", list(range(dzis.year - 2, dzis.year + 1)), index=2)

        numer_miesiaca = nazwy_miesiecy.index(wybrany_miesiac) + 1
        pierwszy_dzien = date(wybrany_rok, numer_miesiaca, 1)
        if numer_miesiaca == 12:
            pierwszy_dzien_kolejnego = date(wybrany_rok + 1, 1, 1)
        else:
            pierwszy_dzien_kolejnego = date(wybrany_rok, numer_miesiaca + 1, 1)
        ostatni_dzien = pierwszy_dzien_kolejnego - timedelta(days=1)

        lekcje_miesiac = db.get_lessons_by_date_range(
            korepetytor_id, pierwszy_dzien.isoformat(), ostatni_dzien.isoformat()
        )

        odbyte = [l for l in lekcje_miesiac if l["status"] == "odbyta"]
        odwolane = [l for l in lekcje_miesiac if l["status"] == "odwolana"]
        godziny_odbyte = sum(l["czas_trwania"] for l in odbyte)

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Odbyte lekcje", len(odbyte))
        with col_b:
            st.metric("Godziny łącznie", godziny_odbyte)
        with col_c:
            st.metric("Odwołane lekcje", len(odwolane))

        if not odbyte:
            st.caption("Brak odbytych lekcji w wybranym miesiącu.")
        else:
            st.markdown("**Rozbicie na uczniów:**")
            podsumowanie_uczniow = {}
            for l in odbyte:
                klucz = f"{l['imie']} {l['nazwisko'] or ''}".strip()
                if klucz not in podsumowanie_uczniow:
                    podsumowanie_uczniow[klucz] = {"lekcje": 0, "godziny": 0.0}
                podsumowanie_uczniow[klucz]["lekcje"] += 1
                podsumowanie_uczniow[klucz]["godziny"] += l["czas_trwania"]

            for uczen, dane in sorted(podsumowanie_uczniow.items()):
                st.write(f"**{uczen}** — {dane['lekcje']} lekcji, {dane['godziny']}h")

# --- WIDOK: KALENDARZ ---
elif menu == "Kalendarz":
    st.header("Kalendarz lekcji")
    pokaz_zapamietany_komunikat()

    lekcje = db.get_all_lessons(korepetytor_id)

    kolory_statusow = {
        "zaplanowana": "#3b82f6",  # niebieski
        "odbyta": "#22c55e",       # zielony
        "odwolana": "#ef4444",     # czerwony
    }

    wydarzenia = []
    for lekcja in lekcje:
        try:
            godzina_start = lekcja["godzina"]
            godzina_h, godzina_m = map(int, godzina_start.split(":"))
            czas_start = f"{lekcja['data']}T{godzina_start}:00"

            # Obliczamy godzinę końcową na podstawie czasu trwania
            minuty_calkowite = godzina_h * 60 + godzina_m + int(lekcja["czas_trwania"] * 60)
            godzina_koniec = f"{(minuty_calkowite // 60) % 24:02d}:{minuty_calkowite % 60:02d}"
            czas_koniec = f"{lekcja['data']}T{godzina_koniec}:00"

            wydarzenia.append({
                "id": str(lekcja["id"]),
                "title": f"{lekcja['imie']} {lekcja['nazwisko'] or ''}".strip(),
                "start": czas_start,
                "end": czas_koniec,
                "color": kolory_statusow.get(lekcja["status"], "#6b7280"),
            })
        except (ValueError, KeyError):
            continue  # pomiń lekcję z nieprawidłowym formatem daty/godziny

    opcje_kalendarza = {
        "initialView": "dayGridMonth",
        "locale": "pl",
        "firstDay": 1,  # tydzień zaczyna się od poniedziałku
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek,timeGridDay",
        },
        "height": 650,
    }

    stan_kalendarza = calendar(events=wydarzenia, options=opcje_kalendarza, key="kalendarz_lekcji")

    st.caption("🔵 Zaplanowana &nbsp;&nbsp; 🟢 Odbyta &nbsp;&nbsp; 🔴 Odwołana", unsafe_allow_html=True)

    # Obsługa kliknięcia w wydarzenie - pokazuje szczegóły i opcję odwołania
    if stan_kalendarza and stan_kalendarza.get("eventClick"):
        kliknieta_lekcja_id = int(stan_kalendarza["eventClick"]["event"]["id"])
        lekcje_wg_id = {l["id"]: l for l in lekcje}
        wybrana_lekcja = lekcje_wg_id.get(kliknieta_lekcja_id)

        if wybrana_lekcja:
            st.divider()
            st.subheader("Wybrana lekcja")
            st.write(f"**{wybrana_lekcja['imie']} {wybrana_lekcja['nazwisko'] or ''}**")
            st.caption(
                f"{wybrana_lekcja['data']} o {wybrana_lekcja['godzina']} "
                f"({wybrana_lekcja['czas_trwania']}h) — "
                f"{ETYKIETY_STATUSOW_LEKCJI.get(wybrana_lekcja['status'], wybrana_lekcja['status'])}"
            )
            if wybrana_lekcja["notatka"]:
                st.caption(f"Notatka: {wybrana_lekcja['notatka']}")

            pokaz_kontrolki_lekcji(wybrana_lekcja, korepetytor_id, "kalendarz")

# --- WIDOK: DODAJ LEKCJĘ ---
elif menu == "Dodaj lekcję":
    st.header("Dodaj nową lekcję")
    pokaz_zapamietany_komunikat()
    uczniowie = db.get_students(korepetytor_id)

    if not uczniowie:
        st.warning("Najpierw dodaj przynajmniej jednego ucznia.")
    else:
        uczniowie_wg_id = {u["id"]: u for u in uczniowie}
        opcje_uczniow = {f"{u['imie']} {u['nazwisko'] or ''} (saldo: {u['pakiet_godzin']}h)": u["id"]
                          for u in uczniowie}

        wybrany = st.selectbox("Uczeń", options=list(opcje_uczniow.keys()))
        dane_wybranego = uczniowie_wg_id[opcje_uczniow[wybrany]]

        data_lekcji = st.date_input("Data", value=date.today())
        godzina_lekcji = st.time_input("Godzina", value=time(16, 0))
        czas_trwania = st.number_input("Czas trwania (h)", value=1.0, step=0.5, min_value=0.5)
        notatka = st.text_input("Notatka (opcjonalnie)")

        cykliczna = st.checkbox("🔁 Lekcja cykliczna (co tydzień)")
        liczba_tygodni = 1
        if cykliczna:
            liczba_tygodni = st.number_input(
                "Liczba tygodni (łącznie z pierwszą lekcją)",
                min_value=2, max_value=52, value=4, step=1
            )
            godzin_lacznie = czas_trwania * liczba_tygodni
            st.caption(f"Zostanie dodanych {liczba_tygodni} lekcji, łącznie {godzin_lacznie}h.")

        if dane_wybranego["email"]:
            wyslij_powiadomienie = st.checkbox("📧 Wyślij powiadomienie e-mailem do ucznia", value=True)
        else:
            wyslij_powiadomienie = False
            st.caption("Uczeń nie ma podanego adresu e-mail - powiadomienie nie zostanie wysłane.")

        if st.button("Dodaj lekcję"):
            uczen_id = opcje_uczniow[wybrany]

            if cykliczna:
                for tydzien in range(liczba_tygodni):
                    data_kolejnej = data_lekcji + timedelta(weeks=tydzien)
                    db.add_lesson(
                        uczen_id=uczen_id,
                        korepetytor_id=korepetytor_id,
                        data=data_kolejnej.isoformat(),
                        godzina=godzina_lekcji.strftime("%H:%M"),
                        czas_trwania=czas_trwania,
                        notatka=notatka
                    )
                zapamietaj_komunikat("success", f"Dodano {liczba_tygodni} lekcji cyklicznych! Godziny odjęte z pakietu ucznia.")

                if wyslij_powiadomienie:
                    tresc = poczta.szablon_powiadomienia_o_serii(
                        dane_wybranego["imie"], data_lekcji.isoformat(),
                        godzina_lekcji.strftime("%H:%M"), czas_trwania, liczba_tygodni
                    )
                    udalo_sie, blad = poczta.wyslij_maila(
                        dane_wybranego["email"], "Nowe lekcje zaplanowane - Korepetytor +", tresc
                    )
                    if not udalo_sie:
                        zapamietaj_komunikat("warning", f"Lekcje dodane, ale nie udało się wysłać powiadomienia e-mail: {blad}")
            else:
                db.add_lesson(
                    uczen_id=uczen_id,
                    korepetytor_id=korepetytor_id,
                    data=data_lekcji.isoformat(),
                    godzina=godzina_lekcji.strftime("%H:%M"),
                    czas_trwania=czas_trwania,
                    notatka=notatka
                )
                zapamietaj_komunikat("success", "Lekcja dodana! Godziny odjęte z pakietu ucznia.")

                if wyslij_powiadomienie:
                    tresc = poczta.szablon_powiadomienia_o_lekcji(
                        dane_wybranego["imie"], data_lekcji.isoformat(),
                        godzina_lekcji.strftime("%H:%M"), czas_trwania
                    )
                    udalo_sie, blad = poczta.wyslij_maila(
                        dane_wybranego["email"], "Przypomnienie o lekcji - Korepetytor +", tresc
                    )
                    if not udalo_sie:
                        zapamietaj_komunikat("warning", f"Lekcja dodana, ale nie udało się wysłać powiadomienia e-mail: {blad}")

            st.rerun()

# --- WIDOK: LISTA UCZNIÓW ---
elif menu == "Lista uczniów":
    st.header("Lista uczniów")
    pokaz_zapamietany_komunikat()

    # Kafelek "Dodaj nowego ucznia" - rozwijany formularz na górze strony
    if st.button("➕ Dodaj nowego ucznia"):
        st.session_state["pokaz_dodaj_ucznia"] = not st.session_state.get("pokaz_dodaj_ucznia", False)

    if st.session_state.get("pokaz_dodaj_ucznia", False):
        with st.container(border=True):
            st.subheader("Nowy uczeń")
            imie_nowy = st.text_input("Imię *", key="nowy_imie")
            nazwisko_nowy = st.text_input("Nazwisko", key="nowy_nazwisko")
            telefon_nowy = st.text_input("Telefon", key="nowy_telefon")
            email_nowy = st.text_input("E-mail (do powiadomień o lekcjach)", key="nowy_email")
            pakiet_godzin_nowy = st.number_input("Liczba godzin w pakiecie", value=0.0, step=0.5, min_value=0.0, key="nowy_pakiet")
            notatki_nowy = st.text_area("Notatki (opcjonalnie)", key="nowe_notatki")

            if st.button("Dodaj ucznia", key="zapisz_nowego_ucznia"):
                if not imie_nowy.strip():
                    st.error("Imię jest wymagane.")
                elif not czy_poprawny_telefon(telefon_nowy):
                    st.error("Numer telefonu wygląda niepoprawnie. Podaj 9 cyfr, opcjonalnie z prefiksem +48 (albo zostaw pole puste).")
                else:
                    db.add_student(korepetytor_id, imie_nowy, nazwisko_nowy, telefon_nowy, pakiet_godzin_nowy, notatki_nowy, email_nowy)
                    st.session_state["pokaz_dodaj_ucznia"] = False
                    st.success(f"Dodano ucznia: {imie_nowy} {nazwisko_nowy}")
                    st.rerun()

        st.divider()

    uczniowie = db.get_students(korepetytor_id)

    if not uczniowie:
        st.info("Brak uczniów w bazie.")
    else:
        szukaj = st.text_input("🔍 Szukaj ucznia po imieniu lub nazwisku")

        if szukaj.strip():
            fraza = szukaj.strip().lower()
            uczniowie = [
                u for u in uczniowie
                if fraza in u["imie"].lower() or fraza in (u["nazwisko"] or "").lower()
            ]

        sortowanie = st.selectbox(
            "Sortuj według",
            ["Imię (A-Z)", "Saldo godzin (rosnąco)", "Saldo godzin (malejąco)"]
        )

        if sortowanie == "Imię (A-Z)":
            uczniowie = sorted(uczniowie, key=lambda u: u["imie"].lower())
        elif sortowanie == "Saldo godzin (rosnąco)":
            uczniowie = sorted(uczniowie, key=lambda u: u["pakiet_godzin"])
        elif sortowanie == "Saldo godzin (malejąco)":
            uczniowie = sorted(uczniowie, key=lambda u: u["pakiet_godzin"], reverse=True)

        if not uczniowie:
            st.info("Brak uczniów pasujących do wyszukiwania.")

        for u in uczniowie:
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
            with col1:
                st.write(f"**{u['imie']} {u['nazwisko'] or ''}**")
                st.caption(f"Tel: {u['telefon'] or 'brak'}")
                if u["notatki"]:
                    st.caption(f"📝 {u['notatki']}")
            with col2:
                saldo = u["pakiet_godzin"]
                if saldo <= 1:
                    st.error(f"Saldo: {saldo}h")
                else:
                    st.success(f"Saldo: {saldo}h")
            with col3:
                if st.button("✏️ Edytuj", key=f"edytuj_{u['id']}"):
                    st.session_state[f"pokaz_edycje_{u['id']}"] = not st.session_state.get(f"pokaz_edycje_{u['id']}", False)
            with col4:
                if st.button("📜 Historia", key=f"historia_{u['id']}"):
                    st.session_state[f"pokaz_historie_{u['id']}"] = not st.session_state.get(f"pokaz_historie_{u['id']}", False)
            with col5:
                if st.session_state.get(f"potwierdz_usun_{u['id']}", False):
                    if st.button("⚠️ Na pewno?", key=f"potwierdz_{u['id']}"):
                        db.delete_student(u["id"], korepetytor_id)
                        st.session_state[f"potwierdz_usun_{u['id']}"] = False
                        st.success(f"Usunięto ucznia: {u['imie']}")
                        st.rerun()
                else:
                    if st.button("🗑️ Usuń", key=f"usun_{u['id']}"):
                        st.session_state[f"potwierdz_usun_{u['id']}"] = True
                        st.rerun()

            # Historia lekcji tego ucznia - pokazuje się po kliknięciu "Historia"
            if st.session_state.get(f"pokaz_historie_{u['id']}", False):
                historia = db.get_lessons_by_student(u["id"], korepetytor_id)
                if not historia:
                    st.caption("Brak lekcji w historii.")
                else:
                    for lekcja in historia:
                        linia = f"{lekcja['data']} {lekcja['godzina']} ({lekcja['czas_trwania']}h)"
                        if lekcja["notatka"]:
                            linia += f" — {lekcja['notatka']}"
                        st.write(linia)
                        pokaz_kontrolki_lekcji(lekcja, korepetytor_id, "historia")
                        st.divider()

            if st.session_state.get(f"pokaz_edycje_{u['id']}", False):
                st.markdown("**Edycja danych ucznia:**")

                if db.czy_uczen_ma_konto(u["id"]):
                    st.caption("✅ Ten uczeń założył już własne konto w aplikacji.")
                else:
                    st.info(f"🔑 Kod zaproszenia dla ucznia (do założenia własnego konta): **{u['kod_zaproszenia']}**")

                nowe_imie = st.text_input("Imię", value=u["imie"], key=f"imie_{u['id']}")
                nowe_nazwisko = st.text_input("Nazwisko", value=u["nazwisko"] or "", key=f"nazwisko_{u['id']}")
                nowy_telefon = st.text_input("Telefon", value=u["telefon"] or "", key=f"telefon_{u['id']}")
                nowy_email = st.text_input("E-mail (do powiadomień o lekcjach)", value=u["email"] or "", key=f"email_{u['id']}")
                nowe_saldo = st.number_input("Saldo godzin", value=float(u["pakiet_godzin"]), step=0.5, key=f"saldo_{u['id']}")
                nowe_notatki = st.text_area(
                    "Notatki (np. materiał, słabe strony, preferencje)",
                    value=u["notatki"] or "",
                    key=f"notatki_{u['id']}"
                )

                col_zapisz, col_anuluj = st.columns([1, 1])
                with col_zapisz:
                    if st.button("💾 Zapisz zmiany", key=f"zapisz_{u['id']}"):
                        if not czy_poprawny_telefon(nowy_telefon):
                            st.error("Numer telefonu wygląda niepoprawnie. Podaj 9 cyfr, opcjonalnie z prefiksem +48 (albo zostaw pole puste).")
                        else:
                            db.update_student(u["id"], korepetytor_id, nowe_imie, nowe_nazwisko, nowy_telefon, nowe_saldo, nowe_notatki, nowy_email)
                            st.session_state[f"pokaz_edycje_{u['id']}"] = False
                            st.success("Zapisano zmiany.")
                            st.rerun()
                with col_anuluj:
                    if st.button("Anuluj", key=f"anuluj_{u['id']}"):
                        st.session_state[f"pokaz_edycje_{u['id']}"] = False
                        st.rerun()

            st.divider()
