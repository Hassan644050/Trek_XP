from app.services.destination.country import get_country_info


def test_known_country_has_plug_data():
    info = get_country_info("BD", "Bangladesh")
    assert info.available
    assert info.plug_types == ["A", "C", "D", "G", "K"]
    assert (info.voltage, info.frequency) == ("220V", "50Hz")


def test_country_code_lookup_ignores_case():
    assert get_country_info("bd").available


def test_unknown_country_keeps_name_but_is_unavailable():
    info = get_country_info("ZZ", "Nowhere")
    assert not info.available
    assert info.country_name == "Nowhere"
    assert info.plug_types == []


def test_missing_country_code_is_unavailable():
    assert not get_country_info(None).available
