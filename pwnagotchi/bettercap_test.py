import pytest

from pwnagotchi.bettercap import extract_error_info_module,extract_error_info_interface,extract_error_info_bssid

class TestExtractErrorInfo:
    def test_unknown_bssid_1(self):
        error_text = "50:a7:de:ee:d3:46 is an unknown BSSID or it is in the association skip list."
        res = extract_error_info_bssid(error_text)
        correct_res = "50:a7:de:ee:d3:46"
        assert correct_res == res

    def test_unknown_bssid_2(self):
        error_text = "is an unknown BSSID or it is in the association skip list."
        # with self.assertRaises(Exception) as context:
        with pytest.raises(ValueError) as exc:
            res = extract_error_info_bssid(error_text)
            print(f"res = {res}")
        assert "no BSSID" in str(exc.value)

    def test_unknown_bssid_3(self):
        error_text = " is an unknown BSSID or it is in the association skip list."
        with pytest.raises(ValueError) as exc:
            res = extract_error_info_bssid(error_text)
            print(f"res = {res}")
        assert "no BSSID" in str(exc.value)

    def test_unknown_bssid_4(self):
        error_text = "notabssid is an unknown BSSID or it is in the association skip list."
        with pytest.raises(ValueError) as exc:
            res = extract_error_info_bssid(error_text)
            print(f"res = {res}")
        assert "invalid BSSID" in str(exc.value)

    def test_module_not_running_0(self):
        error_text = "module wifi is not running"
        res = extract_error_info_module(error_text)
        correct_res = "wifi"
        assert correct_res == res

    def test_module_not_running_1(self):
        error_text = "module mac.changer is not running"
        res = extract_error_info_module(error_text)
        correct_res = "mac.changer"
        assert correct_res == res

    def test_module_not_running_2(self):
        error_text = "module is not running"
        with pytest.raises(ValueError) as exc:
            res = extract_error_info_module(error_text)
            print(f"res = {res}")

    def test_couldnt_find_interface_0(self):
        error_text = "could not find interface wlan0mon: no interface matching 'wlan0mon' found."
        res = extract_error_info_interface(error_text)
        correct_res = ('wlan0mon', "no interface matching 'wlan0mon' found.")
        assert correct_res == res

    def test_couldnt_find_interface_1(self):
        error_text = "could not find interface wlan1mon: no interface matching 'wlan1mon' found."
        res = extract_error_info_interface(error_text)
        correct_res = ('wlan1mon', "no interface matching 'wlan1mon' found.")
        assert correct_res == res

    def test_couldnt_find_interface_2(self):
        error_text = "could not find interface wlan0mon"
        res = extract_error_info_interface(error_text)
        correct_res = ('wlan0mon', None)
        assert correct_res == res

    def test_couldnt_find_interface_3(self):
        error_text = "could not find interface wlan0mon: no interface matching 'wlan0mon' found : reason2 : reason3"
        res = extract_error_info_interface(error_text)
        correct_res = ('wlan0mon', "no interface matching 'wlan0mon' found : reason2 : reason3")
        assert correct_res == res

    def test_couldnt_find_interface_4(self):
        error_text = "could not find interface"
        self.raises_extract_error_info_interface(error_text)
    def test_couldnt_find_interface_5(self):
        error_text = "could not find interface "
        self.raises_extract_error_info_interface(error_text)
    def test_couldnt_find_interface_6(self):
        error_text = "could not find interface : "
        self.raises_extract_error_info_interface(error_text)

    def raises_extract_error_info_interface(self, error_text):
        with pytest.raises(ValueError) as exc:
            res = extract_error_info_interface(error_text)
            print(f"res = {res}")
