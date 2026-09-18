"""
db_backend.py
Warstwa zgodności, dzięki której database.py może działać zarówno na
lokalnym pliku SQLite (do szybkich testów na Twoim komputerze), jak i na
Turso - bazie zgodnej z SQLite, hostowanej w chmurze, trwałej niezależnie
od tego, że Streamlit Cloud okresowo czyści system plików kontenera.

Jeśli w st.secrets istnieje sekcja [turso] z "url" i "auth_token", używana
jest baza w chmurze. W przeciwnym razie - zwykły lokalny plik SQLite,
dokładnie tak jak dotychczas. Reszta database.py (wszystkie zapytania SQL)
zostaje bez zmian - ta warstwa tylko "podszywa się" pod interfejs
połączenia/kursora sqlite3, żeby nic więcej nie trzeba było przepisywać.

WAŻNA UWAGA: integracja z Turso (biblioteka libsql_client) została napisana
na podstawie dokumentacji tej biblioteki, bez możliwości przetestowania na
żywo w tym środowisku. Jeśli po skonfigurowaniu sekretów pojawi się błąd
związany z nazwą metody/atrybutu w libsql_client, to najbardziej
prawdopodobne miejsce do poprawki - da się to szybko skorygować.
"""

import sqlite3

try:
    import streamlit as st
except ImportError:
    st = None

try:
    import libsql_client
except ImportError:
    libsql_client = None


def turso_skonfigurowane():
    """Sprawdza, czy w sekretach są kompletne dane dostępowe do Turso."""
    if st is None or libsql_client is None:
        return False
    try:
        return "turso" in st.secrets and "url" in st.secrets["turso"] and "auth_token" in st.secrets["turso"]
    except Exception:
        return False


class _WierszLibsql:
    """Opakowuje wiersz zwrócony przez Turso, żeby zachowywał się jak sqlite3.Row (dostęp przez nazwę kolumny)."""

    def __init__(self, kolumny, wartosci):
        self._mapa = dict(zip(kolumny, wartosci))

    def __getitem__(self, klucz):
        return self._mapa[klucz]

    def keys(self):
        return self._mapa.keys()

    def get(self, klucz, domyslnie=None):
        return self._mapa.get(klucz, domyslnie)


class _KursorLibsql:
    """Opakowuje klienta libsql, imitując interfejs kursora sqlite3 (execute/fetchone/fetchall/lastrowid)."""

    def __init__(self, klient):
        self._klient = klient
        self._wynik = None

    def execute(self, sql, parametry=()):
        self._wynik = self._klient.execute(sql, list(parametry))
        return self

    def fetchone(self):
        if not self._wynik.rows:
            return None
        return _WierszLibsql(self._wynik.columns, self._wynik.rows[0])

    def fetchall(self):
        return [_WierszLibsql(self._wynik.columns, w) for w in self._wynik.rows]

    @property
    def lastrowid(self):
        return self._wynik.last_insert_rowid


class _PolaczenieLibsql:
    """
    Opakowuje klienta libsql, imitując interfejs połączenia sqlite3
    (cursor/commit/close). Sam klient jest tworzony RAZ i przechowywany
    współdzielony (patrz _pobierz_wspolny_klient_turso) - żeby uniknąć
    zakładania nowego połączenia sieciowego z Turso przy każdym pojedynczym
    zapytaniu, co bardzo spowalniało działanie aplikacji.
    """

    def __init__(self, url, token):
        self._klient = _pobierz_wspolny_klient_turso(url, token)

    def cursor(self):
        return _KursorLibsql(self._klient)

    def commit(self):
        pass  # libsql_client zapisuje zmiany od razu przy każdym execute()

    def close(self):
        pass  # połączenie jest współdzielone między wywołaniami - naprawdę
              # zamykać będziemy je dopiero przy zamknięciu procesu aplikacji


_wspolny_klient_turso = None


def _pobierz_wspolny_klient_turso(url, token):
    """
    Zwraca jedno, długożyjące połączenie z Turso, tworzone tylko przy
    pierwszym użyciu w danym procesie aplikacji, a potem używane ponownie
    do wszystkich kolejnych zapytań (zamiast łączyć się od nowa za każdym
    razem).
    """
    global _wspolny_klient_turso
    if _wspolny_klient_turso is None:
        # Adres w formacie "libsql://..." używa domyślnie połączenia przez
        # WebSocket, które nie zawsze działa poprawnie w środowiskach takich
        # jak Streamlit Cloud (może być blokowane albo źle obsługiwane przez
        # sieć hostingu). Zamieniamy na "https://" - ten sam serwer Turso,
        # ale połączenie przez zwykłe HTTPS, dużo bardziej niezawodne.
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        _wspolny_klient_turso = libsql_client.create_client_sync(url=url, auth_token=token)
    return _wspolny_klient_turso


def polacz(nazwa_pliku_sqlite):
    """
    Zwraca połączenie z bazą danych - z Turso, jeśli skonfigurowane w
    sekretach (st.secrets["turso"]), w przeciwnym razie ze zwykłym lokalnym
    plikiem SQLite (dotychczasowe zachowanie, bez żadnej zmiany).
    """
    if turso_skonfigurowane():
        return _PolaczenieLibsql(st.secrets["turso"]["url"], st.secrets["turso"]["auth_token"])

    conn = sqlite3.connect(nazwa_pliku_sqlite)
    conn.row_factory = sqlite3.Row
    return conn
