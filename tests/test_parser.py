"""Testes do parser.

Como rodar:
    pytest tests/test_parser.py          # com pytest (recomendado)
    python tests/test_parser.py           # sem dependências extras

O 'now' fixo é 2026-05-10 12:00 — referência pra testar year inference
(datas no passado devem virar próximo ano).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import ParsedEvent, ParseError  # noqa: E402
from src.parser import parse  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 5, 10, 12, 0, tzinfo=TZ)


# ---------------- happy paths (os 6 exemplos do README) ----------------

def test_simple_time_default_1h():
    r = parse("Dentista 18/05 16:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Dentista"
    assert r.start == datetime(2026, 5, 18, 16, 0, tzinfo=TZ)
    assert r.end == datetime(2026, 5, 18, 17, 0, tzinfo=TZ)
    assert r.is_all_day is False
    assert r.location is None and r.notes is None


def test_explicit_range():
    r = parse("Aula 15/05 19:00-21:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Aula"
    assert r.start == datetime(2026, 5, 15, 19, 0, tzinfo=TZ)
    assert r.end == datetime(2026, 5, 15, 21, 0, tzinfo=TZ)


def test_duration_minutes():
    r = parse("Reunião 18/05 14:00 +30m", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.end == datetime(2026, 5, 18, 14, 30, tzinfo=TZ)


def test_duration_hours_and_minutes():
    r = parse("Reunião 18/05 14:00 +1h30m", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.end == datetime(2026, 5, 18, 15, 30, tzinfo=TZ)


def test_duration_hours_only():
    r = parse("Reunião 18/05 14:00 +2h", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.end == datetime(2026, 5, 18, 16, 0, tzinfo=TZ)


def test_with_location():
    r = parse("Festa do Greg 01/06 20:00 @ casa do Greg", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Festa do Greg"
    assert r.location == "casa do Greg"
    assert r.notes is None


def test_all_day_no_time():
    r = parse("Aniversário do João 12/07", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Aniversário do João"
    assert r.is_all_day is True
    assert r.start == datetime(2026, 7, 12, 0, 0, tzinfo=TZ)
    # convenção do Google: end exclusivo (1 dia → +1 dia)
    assert r.end == datetime(2026, 7, 13, 0, 0, tzinfo=TZ)


def test_location_and_notes():
    r = parse("Prova 22/05 14:00 @ FCT # cadeira de SO", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Prova"
    assert r.location == "FCT"
    assert r.notes == "cadeira de SO"


# ---------------- variações ----------------

def test_multi_word_title():
    r = parse("Reunião com gerente 18/05 14:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Reunião com gerente"


def test_explicit_year_4_digits():
    r = parse("Dentista 18/05/2030 16:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.year == 2030


def test_two_digit_year():
    r = parse("Dentista 18/05/27 16:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.year == 2027


def test_explicit_year_in_past_is_kept():
    # ano explícito no passado é respeitado (não bumpa)
    r = parse("Reunião 01/01/2020 09:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.year == 2020


# ---------------- year inference ----------------

def test_past_date_bumps_to_next_year():
    # now = 2026-05-10. "03/05" já passou em 2026 → vira 2027.
    r = parse("Dentista 03/05 10:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.year == 2027


def test_today_is_not_past():
    # hoje (10/05) não é passado
    r = parse("Dentista 10/05 18:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.year == 2026


def test_future_date_keeps_current_year():
    r = parse("Dentista 30/12 18:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.year == 2026


# ---------------- datas relativas ----------------
# NOW = 2026-05-10, que é um domingo (weekday=6).

def test_relative_hoje():
    r = parse("Dentista hoje 16:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Dentista"
    assert r.start.date() == datetime(2026, 5, 10).date()


def test_relative_amanha():
    r = parse("Dentista amanhã 16:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Dentista"
    assert r.start.date() == datetime(2026, 5, 11).date()


def test_relative_amanha_sem_acento():
    r = parse("Dentista amanha 16:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 11).date()


def test_relative_amanha_uppercase():
    r = parse("Dentista AMANHÃ 16:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 11).date()


def test_relative_depois_de_amanha():
    r = parse("Festa depois de amanhã 20:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 12).date()


def test_relative_weekday_segunda():
    # domingo (10/05) → próxima segunda é amanhã (11/05)
    r = parse("Reunião segunda 14:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 11).date()


def test_relative_weekday_sexta():
    # domingo (10/05) → próxima sexta é 15/05
    r = parse("Happy hour sexta 19:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 15).date()


def test_relative_weekday_domingo_today_is_sunday():
    # IMPORTANTE: hoje é domingo. "domingo" deve pular pra domingo que vem.
    r = parse("Almoço domingo 13:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 17).date()


def test_relative_weekday_with_feira():
    r = parse("Aula terça-feira 19:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 12).date()


def test_relative_weekday_sem_acento():
    r = parse("Reunião sabado 10:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.start.date() == datetime(2026, 5, 16).date()


def test_explicit_date_overrides_relative_word():
    # Se tem DD/MM no texto, palavras relativas ficam no título.
    r = parse("Aula de domingo 18/05 14:00", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.title == "Aula de domingo"
    assert r.start.date() == datetime(2026, 5, 18).date()


def test_relative_all_day():
    # "amanhã" sem hora → all-day
    r = parse("Aniversário amanhã", NOW)
    assert isinstance(r, ParsedEvent)
    assert r.is_all_day is True
    assert r.start.date() == datetime(2026, 5, 11).date()


# ---------------- erros ----------------

def test_empty_message():
    assert isinstance(parse("", NOW), ParseError)


def test_no_date():
    assert isinstance(parse("lixo aleatório", NOW), ParseError)


def test_invalid_date_99_99():
    assert isinstance(parse("lixo 99/99", NOW), ParseError)


def test_invalid_date_30_02():
    assert isinstance(parse("almoço 30/02 12:00", NOW), ParseError)


def test_missing_title():
    assert isinstance(parse("18/05 16:00", NOW), ParseError)


def test_end_before_start():
    assert isinstance(parse("aula 18/05 16:00-14:00", NOW), ParseError)


def test_invalid_hour():
    # 25:99 — hora inválida
    assert isinstance(parse("dentista 18/05 25:99", NOW), ParseError)


def test_garbage_after_time():
    assert isinstance(parse("dentista 18/05 16:00 banana", NOW), ParseError)


# ---------------- runner standalone ----------------

if __name__ == "__main__":
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed: list[str] = []
    for name, fn in tests:
        try:
            fn()
            print(f"  [OK]   {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}: AssertionError {e}")
            failed.append(name)
        except Exception as e:
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
