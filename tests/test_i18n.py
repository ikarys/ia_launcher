from hominfer import i18n


def test_every_locale_has_every_english_key():
    english = set(i18n.LOCALES["en"])
    for lang, texts in i18n.LOCALES.items():
        assert english - set(texts) == set(), lang


def test_tr_fills_known_placeholders_and_keeps_others():
    assert i18n.tr("run.port_busy", port=8000) == "Port 8000 is already used by another program."
    assert "{param}" in i18n.tr("cfg.command")


def test_tr_falls_back_to_english_then_to_the_key():
    i18n.set_lang("fr")
    assert i18n.tr("run.already") == "Déjà lancé."
    assert i18n.tr("no.such.key") == "no.such.key"


def test_loc_and_numbers():
    assert i18n.loc({"en": "Context", "fr": "Contexte"}) == "Context"
    assert i18n.loc("plain") == "plain"
    i18n.set_lang("fr")
    assert i18n.loc({"en": "Context", "fr": "Contexte"}) == "Contexte"
    assert i18n.gib(1536) == "1,5 Go"
