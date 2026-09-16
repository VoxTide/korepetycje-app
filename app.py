"""
app.py
Interfejs Streamlit dla systemu rezerwacji korepetycji, z kontami użytkowników.

Uruchomienie lokalne:
    streamlit run app.py
"""

import streamlit as st
from datetime import date, time
import database as db

db.init_db()

st.set_page_config(page_title="System rezerwacji korepetycji", page_icon="📚")


# --- EKRAN LOGOWANIA / REJESTRACJI ---
# Pokazuje się zawsze, gdy nikt nie jest zalogowany (sprawdzamy przez session_state)

def pokaz_ekran_logowania():
    st.title("📚 System rezerwacji korepetycji")

    tab_logowanie, tab_rejestracja = st.tabs(["Zaloguj się", "Załóż konto"])

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
        nowe_haslo = st.text_input("Wybierz hasło", type="password", key="haslo_rejestracja")
        powtorz_haslo = st.text_input("Powtórz hasło", type="password", key="haslo_rejestracja_2")

        if st.button("Załóż konto"):
            if not nowy_login or not nowe_haslo:
                st.error("Wypełnij wszystkie pola.")
            elif nowe_haslo != powtorz_haslo:
                st.error("Hasła nie są identyczne.")
            elif len(nowe_haslo) < 4:
                st.error("Hasło musi mieć co najmniej 4 znaki.")
            else:
                try:
                    db.create_user(nowy_login, nowe_haslo)
                    st.success("Konto utworzone! Możesz się teraz zalogować w zakładce obok.")
                except ValueError as e:
                    st.error(str(e))


# --- SPRAWDZENIE, CZY UŻYTKOWNIK JEST ZALOGOWANY ---

if "user_id" not in st.session_state:
    pokaz_ekran_logowania()
    st.stop()  # zatrzymuje wykonywanie reszty skryptu, dopóki ktoś się nie zaloguje

# Od tego miejsca w dół — użytkownik jest już zalogowany
korepetytor_id = st.session_state["user_id"]

# --- PASEK BOCZNY ---
st.sidebar.write(f"Zalogowano jako: **{st.session_state['login']}**")
if st.sidebar.button("Wyloguj się"):
    del st.session_state["user_id"]
    del st.session_state["login"]
    st.rerun()

# Usuwanie konta - z dwuetapowym potwierdzeniem, tak jak przy usuwaniu ucznia
if st.session_state.get("potwierdz_usun_konto", False):
    st.sidebar.warning("Usunięcie konta jest nieodwracalne — stracisz wszystkich uczniów i lekcje.")
    col_tak, col_nie = st.sidebar.columns(2)
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
    if st.sidebar.button("🗑️ Usuń konto"):
        st.session_state["potwierdz_usun_konto"] = True
        st.rerun()

st.sidebar.divider()

menu = st.sidebar.radio(
    "Menu",
    ["Nadchodzące lekcje", "Dodaj lekcję", "Lista uczniów", "Dodaj ucznia"]
)

st.title("📚 System rezerwacji korepetycji")

# --- WIDOK: NADCHODZĄCE LEKCJE ---
if menu == "Nadchodzące lekcje":
    st.header("Nadchodzące lekcje")

    filtruj = st.checkbox("Filtruj po dacie")
    if filtruj:
        col_a, col_b = st.columns(2)
        with col_a:
            data_od = st.date_input("Od", value=date.today())
        with col_b:
            data_do = st.date_input("Do", value=date.today())
        lekcje = db.get_lessons_by_date_range(korepetytor_id, data_od.isoformat(), data_do.isoformat())
        lekcje = [l for l in lekcje if l["status"] == "zaplanowana"]
    else:
        lekcje = db.get_upcoming_lessons(korepetytor_id)

    if not lekcje:
        st.info("Brak zaplanowanych lekcji.")
    else:
        for lekcja in lekcje:
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                st.write(f"**{lekcja['imie']} {lekcja['nazwisko'] or ''}**")
                st.caption(f"{lekcja['data']} o {lekcja['godzina']} ({lekcja['czas_trwania']}h)")
            with col2:
                if lekcja["notatka"]:
                    st.caption(f"Notatka: {lekcja['notatka']}")
            with col3:
                if st.button("Odbyta", key=f"odbyta_{lekcja['id']}"):
                    db.mark_lesson_status(lekcja["id"], korepetytor_id, "odbyta")
                    st.rerun()
                if st.button("Odwołaj", key=f"odwolaj_{lekcja['id']}"):
                    db.cancel_lesson(lekcja["id"], korepetytor_id)
                    st.rerun()
            st.divider()

# --- WIDOK: DODAJ LEKCJĘ ---
elif menu == "Dodaj lekcję":
    st.header("Dodaj nową lekcję")
    uczniowie = db.get_students(korepetytor_id)

    if not uczniowie:
        st.warning("Najpierw dodaj przynajmniej jednego ucznia.")
    else:
        opcje_uczniow = {f"{u['imie']} {u['nazwisko'] or ''} (saldo: {u['pakiet_godzin']}h)": u["id"]
                          for u in uczniowie}

        wybrany = st.selectbox("Uczeń", options=list(opcje_uczniow.keys()))
        data_lekcji = st.date_input("Data", value=date.today())
        godzina_lekcji = st.time_input("Godzina", value=time(16, 0))
        czas_trwania = st.number_input("Czas trwania (h)", value=1.0, step=0.5, min_value=0.5)
        notatka = st.text_input("Notatka (opcjonalnie)")

        if st.button("Dodaj lekcję"):
            uczen_id = opcje_uczniow[wybrany]
            db.add_lesson(
                uczen_id=uczen_id,
                korepetytor_id=korepetytor_id,
                data=data_lekcji.isoformat(),
                godzina=godzina_lekcji.strftime("%H:%M"),
                czas_trwania=czas_trwania,
                notatka=notatka
            )
            st.success("Lekcja dodana! Godziny odjęte z pakietu ucznia.")
            st.rerun()

# --- WIDOK: LISTA UCZNIÓW ---
elif menu == "Lista uczniów":
    st.header("Lista uczniów")
    uczniowie = db.get_students(korepetytor_id)

    if not uczniowie:
        st.info("Brak uczniów w bazie.")
    else:
        for u in uczniowie:
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.write(f"**{u['imie']} {u['nazwisko'] or ''}**")
                st.caption(f"Tel: {u['telefon'] or 'brak'}")
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

            if st.session_state.get(f"pokaz_edycje_{u['id']}", False):
                st.markdown("**Edycja danych ucznia:**")
                nowe_imie = st.text_input("Imię", value=u["imie"], key=f"imie_{u['id']}")
                nowe_nazwisko = st.text_input("Nazwisko", value=u["nazwisko"] or "", key=f"nazwisko_{u['id']}")
                nowy_telefon = st.text_input("Telefon", value=u["telefon"] or "", key=f"telefon_{u['id']}")
                nowe_saldo = st.number_input("Saldo godzin", value=float(u["pakiet_godzin"]), step=0.5, key=f"saldo_{u['id']}")

                col_zapisz, col_anuluj = st.columns([1, 1])
                with col_zapisz:
                    if st.button("💾 Zapisz zmiany", key=f"zapisz_{u['id']}"):
                        db.update_student(u["id"], korepetytor_id, nowe_imie, nowe_nazwisko, nowy_telefon, nowe_saldo)
                        st.session_state[f"pokaz_edycje_{u['id']}"] = False
                        st.success("Zapisano zmiany.")
                        st.rerun()
                with col_anuluj:
                    if st.button("Anuluj", key=f"anuluj_{u['id']}"):
                        st.session_state[f"pokaz_edycje_{u['id']}"] = False
                        st.rerun()

            st.divider()

# --- WIDOK: DODAJ UCZNIA ---
elif menu == "Dodaj ucznia":
    st.header("Dodaj nowego ucznia")

    imie = st.text_input("Imię *")
    nazwisko = st.text_input("Nazwisko")
    telefon = st.text_input("Telefon")
    pakiet_godzin = st.number_input("Liczba godzin w pakiecie", value=0.0, step=0.5, min_value=0.0)

    if st.button("Dodaj ucznia"):
        if not imie.strip():
            st.error("Imię jest wymagane.")
        else:
            db.add_student(korepetytor_id, imie, nazwisko, telefon, pakiet_godzin)
            st.success(f"Dodano ucznia: {imie} {nazwisko}")
            st.rerun()
