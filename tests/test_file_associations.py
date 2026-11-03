from xref import file_associations


class FakeWinreg:
    HKEY_CURRENT_USER = 'HKCU'
    KEY_SET_VALUE = 2
    REG_NONE = 0
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    def CreateKeyEx(self, root, path, reserved, access):
        assert root == self.HKEY_CURRENT_USER
        assert access == self.KEY_SET_VALUE
        return path

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values[(key, name)] = (value_type, value)

    @staticmethod
    def CloseKey(key):
        pass


def test_registers_both_board_extensions_with_quoted_command():
    winreg = FakeWinreg()
    executable = r'C:\Program Files\XRef\XRef.exe'

    file_associations._register_with_winreg(winreg, executable)

    assert winreg.values[
        (r'Software\Classes\XRef.Board\shell\open\command', '')] == (
            winreg.REG_SZ, f'"{executable}" "%1"')
    for extension in ('.xref', '.bee'):
        assert winreg.values[(rf'Software\Classes\{extension}', '')] == (
            winreg.REG_SZ, file_associations.PROG_ID)
        assert winreg.values[
            (rf'Software\Classes\{extension}\OpenWithProgids',
             file_associations.PROG_ID)] == (winreg.REG_NONE, b'')
        assert winreg.values[
            (rf'{file_associations.CAPABILITIES_KEY}\FileAssociations',
             extension)] == (winreg.REG_SZ, file_associations.PROG_ID)


def test_windows_frozen_app_registers_associations(monkeypatch):
    winreg = FakeWinreg()
    monkeypatch.setattr(file_associations.sys, 'platform', 'win32')
    monkeypatch.setattr(file_associations.sys, 'frozen', True, raising=False)
    monkeypatch.setitem(file_associations.sys.modules, 'winreg', winreg)

    file_associations.register_windows_file_associations()

    assert winreg.values[
        (file_associations.REGISTERED_APPLICATIONS_KEY, 'XRef')] == (
            winreg.REG_SZ, file_associations.CAPABILITIES_KEY)


def test_source_run_does_not_register_file_associations(monkeypatch):
    monkeypatch.setattr(file_associations.sys, 'frozen', False, raising=False)

    assert file_associations.register_windows_file_associations() is None
