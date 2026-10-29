# This file is part of XRef.
#
# XRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# XRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with XRef.  If not, see <https://www.gnu.org/licenses/>.

"""Translation support.

Source strings are English and are wrapped in :func:`tr`. Translations
live in :data:`TRANSLATIONS`, keyed by language code. A missing entry
falls back to the English source, so a partially translated language
never shows blank labels. ``tests/test_i18n.py`` verifies that every
``tr`` string in the package has a Turkish translation.
"""

import logging

from PyQt6 import QtCore


logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = 'en'

#: Language code -> name shown in the UI (native spelling)
LANGUAGES = {
    'en': 'English',
    'tr': 'Türkçe',
}

#: The right-click key hint shown in menus, per language
CONTEXT_MENU_HINT = {
    'en': 'Right-click for more options.',
    'tr': 'Daha fazla seçenek için sağ tıklayın.',
}

TRANSLATIONS = {
    'tr': {
        # -- Menus ---------------------------------------------------------
        '&File': '&Dosya',
        'Open &Recent': '&Son Açılanlar',
        '&Edit': '&Düzen',
        '&View': '&Görünüm',
        '&Insert': '&Ekle',
        '&Transform': '&Dönüştür',
        '&Normalize': '&Normalleştir',
        '&Arrange': '&Yerleştir',
        '&Images': '&Görseller',
        '&Video': '&Video',
        '&Tools': '&Araçlar',
        '&Collaborate': '&Birlikte Çalış',
        '&Settings': '&Ayarlar',
        '&Help': '&Yardım',

        # -- Actions -------------------------------------------------------
        '&Open': '&Aç',
        '&Save': '&Kaydet',
        'Save &As...': 'Farklı &Kaydet...',
        'E&xport Scene...': 'Sahneyi &Dışa Aktar...',
        'Export &Images...': '&Görselleri Dışa Aktar...',
        '&Quit': '&Çıkış',
        '&Images / PDFs...': '&Görseller / PDF\'ler...',
'&Images...': '&Görseller...',
        '&Video...': '&Video...',
        '&Play Video': 'Videoyu &Oynat',
        'Click to lock this frame': 'Bu kareyi kilitlemek için tıklayın',
        'Click to browse the frames again':
            'Kareler arasında gezinmek için tekrar tıklayın',
        'Click to lock this page': 'Bu sayfayı kilitlemek için tıklayın',
        'Click to browse the pages again':
            'Sayfalar arasında gezinmek için tekrar tıklayın',
        '&Draw (Pen Mode)': '&Çiz (Kalem Modu)',
        'Pen &Colour...': 'Kalem &Rengi...',
        'Brush &Thin': 'Fırça &İnce',
        'Brush &Normal': 'Fırça &Normal',
        'Brush Thic&k': 'Fırça &Kalın',
        'Brush &Huge': 'Fırça Çok &Kalın',
        '&Link Selected Items': 'Seçili Öğeleri &Bağla',
        'Remove Lin&ks from Selected Items':
            'Seçili Öğelerin &Bağlantılarını Kaldır',
        '&Share Board...': 'Panoyu &Paylaş...',
        '&Join Shared Board...': 'Paylaşılan Panoya &Katıl...',
        'Show Session &Code': 'Oturum &Kodunu Göster',
        '&Ask Before Peers Join': 'Eşler Katılmadan &Önce Sor',
        '&Stop Sharing': 'Paylaşımı D&urdur',
        '&Text': '&Metin',
        '&Undo': '&Geri Al',
        '&Redo': '&İleri Al',
        '&Copy': '&Kopyala',
        'Cu&t': 'Ke&s',
        '&Paste': '&Yapıştır',
        '&Delete': '&Sil',
        '&Raise to Top': 'En &Üste Taşı',
        'Lower to Bottom': 'En &Alta Taşı',
        '&Height': '&Yüksekliğe Göre',
        '&Width': '&Genişliğe Göre',
        '&Size': '&Boyuta Göre',
        '&Optimal': '&Optimal',
        '&Horizontal (by filename)': '&Yatay (dosya adına göre)',
        '&Vertical (by filename)': '&Dikey (dosya adına göre)',
        '&Square (by filename)': '&Kare (dosya adına göre)',
        'Change &Opacity...': '&Opaklığı Değiştir...',
        '&Grayscale': '&Gri Tonlama',
        'Show &Color Gamut': '&Renk Aralığını Göster',
        'Sample Color': 'Renk Örnekle',
        '&Crop': '&Kırp',
        'Flip &Horizontally': '&Yatay Çevir',
        'Flip &Vertically': '&Dikey Çevir',
        '&New Scene': '&Yeni Sahne',
        '&Fit Scene': 'Sahneye &Sığdır',
        'Fit &Selection': '&Seçime Sığdır',
        'Reset &Scale': '&Ölçeği Sıfırla',
        'Reset &Rotation': '&Döndürmeyi Sıfırla',
        'Reset &Flip': '&Çevirmeyi Sıfırla',
        'Reset Cro&p': '&Kırpmayı Sıfırla',
        'Reset &All': '&Tümünü Sıfırla',
        '&Select All': '&Tümünü Seç',
        'Deselect &All': 'Seçimi &Kaldır',
        '&About': '&Hakkında',
        'Show &Debug Log': '&Hata Ayıklama Kaydını Göster',
        'Show &Scrollbars': '&Kaydırma Çubuklarını Göster',
        'Show &Menu Bar': '&Menü Çubuğunu Göster',
        'Show &Title Bar': '&Başlık Çubuğunu Göster',
        'Move &Window': '&Pencereyi Taşı',
        '&Fullscreen': '&Tam Ekran',
        '&Always On Top': '&Her Zaman Üstte',
        '&Keyboard && Mouse': '&Klavye ve Fare',
        '&Open Settings Folder': 'Ayar &Klasörünü Aç',
        'Show &Menubar': '&Menü Çubuğunu Göster',

        # -- Window title / general ----------------------------------------
        'Untitled': 'Adsız',
        'shared ({count})': 'paylaşılıyor ({count})',
        '{app} Help': '{app} Yardım',
        '{app} Debug Log': '{app} Hata Ayıklama Kaydı',
        '{app} Settings': '{app} Ayarları',
        'About {app}': '{app} Hakkında',

        # -- Common buttons ------------------------------------------------
        'Cancel': 'İptal',
        'Ok': 'Tamam',
        '&Restore Defaults': '&Varsayılanlara Dön',
        'Co&py To Clipboard': 'Panoya &Kopyala',
        'Do you want to restore all settings to their default values?':
            'Tüm ayarlar varsayılan değerlerine döndürülsün mü?',
        'Restore defaults?': 'Varsayılanlara dönülsün mü?',

        # -- Messages ------------------------------------------------------
        'Discard unsaved changes?': 'Kaydedilmemiş değişiklikler atılsın mı?',
        'Problem loading file': 'Dosya yüklenirken sorun oluştu',
        'Problem saving file': 'Dosya kaydedilirken sorun oluştu',
        'Problem writing file': 'Dosya yazılırken sorun oluştu',
        'Problem loading images': 'Görseller yüklenirken sorun oluştu',
        '<p>Problem loading file {filename}</p>'
        '<p>Not accessible or not a proper bee file</p>':
            '<p>{filename} dosyası yüklenemedi</p>'
            '<p>Erişilemiyor veya geçerli bir bee dosyası değil</p>',
        '<p>Problem saving file {filename}</p>'
        '<p>File/directory not accessible</p>':
            '<p>{filename} dosyası kaydedilemedi</p>'
            '<p>Dosya/klasör erişilebilir değil</p>',
        '<p>Problem writing file {filename}</p><p>{error}</p>':
            '<p>{filename} dosyası yazılamadı</p><p>{error}</p>',
        'Open file': 'Dosya aç',
        'Save file': 'Dosya kaydet',
        'Export Images': 'Görselleri Dışa Aktar',
        'Select one or more images or PDFs to open':
    'Bir veya daha fazla görsel ya da PDF seçin',
'Select one or more images to open':
            'Açmak için bir veya daha fazla görsel seçin',
        'Select one or more videos to open':
            'Açmak için bir veya daha fazla video seçin',
        'There are unsaved changes. Are you sure you want to open a new '
        'scene?':
            'Kaydedilmemiş değişiklikler var. Yeni bir sahne açmak '
            'istediğinize emin misiniz?',
        'There are unsaved changes. Are you sure you want to quit?':
            'Kaydedilmemiş değişiklikler var. Çıkmak istediğinize emin '
            'misiniz?',
        'unknown device': 'bilinmeyen cihaz',
        'Nothing could be inserted from the dropped data':
            'Bırakılan veriden hiçbir şey eklenemedi',
        'Unknown format or too big?\n'
        'Check Settings -> Images & Items -> Maximum Image Size':
            'Bilinmeyen biçim veya çok büyük?\n'
            'Ayarlar -> Görseller ve Öğeler -> Maksimum Görsel Boyutu',
        'Copied color to clipboard: {name}':
            'Renk panoya kopyalandı: {name}',
        'File exists': 'Dosya mevcut',
        'File already exists:\n{filename}': 'Dosya zaten var:\n{filename}',
        'Skip this file': 'Bu dosyayı atla',
        'Skip all existing files': 'Tüm mevcut dosyaları atla',
        'Overwrite this file': 'Bu dosyanın üzerine yaz',
        'Overwrite all existing files':
            'Tüm mevcut dosyaların üzerine yaz',
        'Export Scene to Image': 'Sahneyi Görsele Aktar',
        'Width:': 'Genişlik:',
        'Height:': 'Yükseklik:',
        'Change Opacity:': 'Opaklığı Değiştir:',
        'Opacity:': 'Opaklık:',
        'Opacity: {value}%': 'Opaklık: {value}%',
        'Color Gamut': 'Renk Aralığı',
        'Threshold:': 'Eşik:',
        'Video source not found:\n{path}': 'Video kaynağı bulunamadı:\n{path}',
        'Page {current} / {total}': 'Sayfa {current} / {total}',

        # -- Items / pen / links -------------------------------------------
        'Select a video item first': 'Önce bir video öğesi seçin',
        'Pen colour: {name}': 'Kalem rengi: {name}',
        'Brush size: {width}px': 'Fırça boyutu: {width}px',
        'Pen mode {state}': 'Kalem modu {state}',
        'on': 'açık',
        'off': 'kapalı',
        'Select exactly two items to link them '
        '(first selected becomes the parent)':
            'Bağlamak için tam olarak iki öğe seçin '
            '(önce seçilen üst öğe olur)',
        'These items are already linked': 'Bu öğeler zaten bağlı',
        'Linked "{source}" -> "{target}"':
            '"{source}" -> "{target}" bağlandı',
        'Removed {count} link(s)': '{count} bağlantı kaldırıldı',
        'Selected items have no links': 'Seçili öğelerin bağlantısı yok',

        # -- Collaboration -------------------------------------------------
        'Sharing': 'Paylaşılıyor',
        'Not sharing': 'Paylaşım yok',
        'Sharing · code {code} · waiting for peers':
            'Paylaşılıyor · kod {code} · eş bekleniyor',
        'Sharing · code {code} · {count} peer(s)':
            'Paylaşılıyor · kod {code} · {count} eş',
        'Connected to {name} · code {code}':
            '{name} ile bağlantı kuruldu · kod {code}',
        'Disconnected': 'Bağlantı kesildi',
        'Looking for the shared board...':
            'Paylaşılan pano aranıyor...',
        'Please enter the session code.':
            'Lütfen oturum kodunu girin.',
        'Please enter the session code':
            'Lütfen oturum kodunu girin',
        'No board found with this code. Check the code and that both '
        'devices are on the same network.':
            'Bu kodla pano bulunamadı. Kodu ve iki cihazın da aynı ağda '
            'olduğunu kontrol edin.',
        'Could not connect to the board: {error}':
            'Panoya bağlanılamadı: {error}',
        'Could not join the board: {reason}':
            'Panoya katılınamadı: {reason}',
        'Could not join the board: no board data':
            'Panoya katılınamadı: pano verisi alınamadı',
        'Could not start sharing: {error}':
            'Paylaşım başlatılamadı: {error}',
        'Connection error: {error}': 'Bağlantı hatası: {error}',
        'no answer from the host': 'sunucudan yanıt gelmedi',
        'the host could not be verified': 'sunucu doğrulanamadı',
        'denied': 'reddedildi',
        # Handshake denial reasons (kept as codes on the wire)
        'wrong session code': 'oturum kodu yanlış',
        'too many attempts': 'çok fazla deneme',
        'version mismatch': 'sürüm uyumsuz',
        'declined by the host': 'sunucu reddetti',
        'You are now hosting the shared board':
            'Paylaşılan panoyu artık siz yönetiyorsunuz',
        'Host connection lost, recovering...':
            'Host bağlantısı koptu, kurtarılıyor...',
        'Reconnected to the shared board':
            'Paylaşılan panoya yeniden bağlandınız',
        'Shared board connection lost':
            'Paylaşılan pano bağlantısı koptu',
        'Taking over sharing (you are the new host)':
            'Paylaşımı devraldınız (yeni host sizsiniz)',
        'The host ended the shared session':
            'Host paylaşılan oturumu sonlandırdı',
        'Shared board: {count} peer(s) connected':
            'Paylaşılan pano: {count} eş bağlı',
        'A session is already running; stop it first':
            'Zaten bir oturum açık; önce durdurun',
        'Share Board': 'Panoyu Paylaş',
        'Join Request': 'Katılma İsteği',
        'Join Shared Board': 'Paylaşılan Panoya Katıl',
        'Session Code': 'Oturum Kodu',
        'This board is not shared': 'Bu pano paylaşılmıyor',
        'Not in a shared session': 'Paylaşılan bir oturumda değilsiniz',
        'Left the shared session': 'Paylaşılan oturumdan ayrıldınız',
        'Joined the shared board ({code})':
            'Paylaşılan panoya katıldınız ({code})',
        'Peers are asked for approval before joining':
            'Eşler katılmadan önce onay istenir',
        'Peers can join without asking': 'Eşler sormadan katılabilir',
        'You are already in a session. Leave it and join another?':
            'Zaten bir oturumdasınız. Ayrılıp başka bir oturuma '
            'katılmak ister misiniz?',
        'Session code (for example K7M4Q-9PXE2):':
            'Oturum kodu (örneğin K7M4Q-9PXE2):',
        'Joining loads the shared board and replaces the items '
        'currently in this window. Continue?':
            'Katılmak paylaşılan panoyu yükler ve bu penceredeki öğelerin '
            'yerine geçer. Devam edilsin mi?',
        '"{name}" ({address}) knows the session code and wants to join '
        'this board.\n\nAllow?':
            '"{name}" ({address}) oturum kodunu biliyor ve bu panoya '
            'katılmak istiyor.\n\nİzin verilsin mi?',
        'This board is now shared.\n\n'
        'Session code:\n\n    {code}\n\n'
        '(The code has been copied to the clipboard.)\n\n'
        'Other users start XRef, choose Collaborate -> Join Shared '
        'Board and type this code. They do not need to know your IP '
        'address.\n\n'
        'The code is never sent over the network, the connection is '
        'encrypted, and you will be asked before anyone joins.\n\n'
        'Note: the board is not saved automatically - use File -> '
        'Save As to keep a copy.':
            'Bu pano artık paylaşılıyor.\n\n'
            'Oturum kodu:\n\n    {code}\n\n'
            '(Kod panoya kopyalandı.)\n\n'
            'Diğer kullanıcılar XRef\'i açar, Birlikte Çalış -> '
            'Paylaşılan Panoya Katıl seçer ve bu kodu yazar. IP adresinizi '
            'bilmesi gerekmez.\n\n'
            'Kod ağ üzerinden hiç gönderilmez, bağlantı şifrelenir ve '
            'biri katılmadan önce size sorulur.\n\n'
            'Not: pano otomatik kaydedilmez - bir kopyasını saklamak için '
            'Dosya -> Farklı Kaydet kullanın.',
        'Session code:\n\n    {code}\n\n{detail}\n\n'
        'The code has been copied to the clipboard.':
            'Oturum kodu:\n\n    {code}\n\n{detail}\n\n'
            'Kod panoya kopyalandı.',
        'Connected to a shared board with code:\n\n    {code}\n\n'
        'The code has been copied to the clipboard.':
            'Şu kodla paylaşılan bir panoya bağlısınız:\n\n    {code}\n\n'
            'Kod panoya kopyalandı.',
        '{count} peer(s) connected.': '{count} eş bağlı.',
        'No one has joined yet.': 'Henüz kimse katılmadı.',

        # -- Settings dialog ------------------------------------------------
        '&Miscellaneous': '&Çeşitli',
        '&Images && Items': '&Görseller ve Öğeler',
        'Language:': 'Dil:',
        'The language of the user interface.': 'Arayüz dili.',
        'Confirm when closing an unsaved file:':
            'Kaydedilmemiş dosya kapatılırken onayla:',
        'When about to close an unsaved file, should XRef ask for '
        'confirmation?':
            'Kaydedilmemiş bir dosya kapatılırken XRef onay istemeli mi?',
        'Confirm when closing': 'Kapatırken onayla',
        'Autosave:': 'Otomatik Kayıt:',
        'Automatically save the board while you work. Only boards '
        'that already have a file are saved.':
            'Çalışırken panoyu otomatik kaydeder. Yalnızca dosyası olan '
            'panolar kaydedilir.',
        'Save automatically': 'Otomatik kaydet',
        'Autosave Interval:': 'Otomatik Kayıt Aralığı:',
        'How often the board is saved automatically (in minutes).':
            'Panonun kaç dakikada bir otomatik kaydedileceği.',
        'Saving {filename}': 'Kaydediliyor: {filename}',
        'Image Storage Format:': 'Görsel Saklama Biçimi:',
        'How images are stored inside bee files.'
        ' Changes will only take effect on newly saved images.':
            'Görsellerin bee dosyası içinde nasıl saklanacağı. '
            'Değişiklikler yalnızca yeni kaydedilen görsellerde geçerli '
            'olur.',
        'Best Guess': 'En Uygun',
        'Small images and images with alpha channel are stored as png,'
        ' everything else as jpg':
            'Küçük görseller ve saydamlık içeren görseller png, '
            'diğerleri jpg olarak saklanır',
        'Always PNG': 'Her Zaman PNG',
        'Lossless, but large bee file': 'Kayıpsız, ama büyük bee dosyası',
        'Always JPG': 'Her Zaman JPG',
        'Small bee file, but lossy and no transparency support':
            'Küçük bee dosyası, ama kayıplı ve saydamlık yok',
        'Always WebP': 'Her Zaman WebP',
        'Lossless or lossy, supports transparency, modern format':
            'Kayıplı veya kayıpsız, saydamlığı destekler, modern biçim',
        'Maximum Image Size:': 'Maksimum Görsel Boyutu:',
        'The maximum image size that can be loaded (in megabytes). '
        'Set to 0 for no limitation.':
            'Yüklenebilecek en büyük görsel boyutu (megabayt). '
            'Sınırsız için 0 girin.',
        'Window Edge Move Area:': 'Pencere Kenarı Taşıma Alanı:',
        'The frameless window has no title bar. Drag this many pixels '
        'inside the window edge to move it; the outermost pixels '
        'resize the window. Set to 0 to disable the move area.':
            'Çerçevesiz pencerenin başlık çubuğu yoktur. Pencereyi taşımak '
            'için kenardan bu kadar piksel içeriden sürükleyin; en dıştaki '
            'pikseller pencereyi boyutlandırır. 0 yazarsanız taşıma alanı '
            'kapanır.',
        'Arrange Gap:': 'Yerleştirme Boşluğu:',
        'The gap between images when using arrange actions.':
            'Yerleştirme işlemlerinde görseller arasındaki boşluk.',
        'Default Arrange Method:': 'Varsayılan Yerleştirme Yöntemi:',
        'How images are arranged when inserted in batch':
            'Görseller toplu eklendiğinde nasıl yerleştirilir',
        'Optimal': 'Optimal',
        'Horizontal (by filename)': 'Yatay (dosya adına göre)',
        'Vertical (by filename)': 'Dikey (dosya adına göre)',
        'Square (by filename)': 'Kare (dosya adına göre)',
        'Arrange Optimal': 'Optimal yerleştir',
        'Arrange Horizontal (by filename)':
            'Yatay yerleştir (dosya adına göre)',
        'Arrange Vertical (by filename)':
            'Dikey yerleştir (dosya adına göre)',
        'Arrannge Square (by filename)':
            'Kare yerleştir (dosya adına göre)',

        # -- Keyboard & mouse controls --------------------------------------
        'Keyboard & Mouse Controls': 'Klavye ve Fare Kontrolleri',
        '&Keyboard Shortcuts': '&Klavye Kısayolları',
        '&Mouse': '&Fare',
        'Mouse &Wheel': 'Fare &Tekerleği',
        'Search...': 'Ara...',
        'Modifiers': 'Değiştiriciler',
        'Mouse Button:': 'Fare Düğmesi:',
        'Save Controls?': 'Kontroller kaydedilsin mi?',
        'Save Shortcut?': 'Kısayol kaydedilsin mi?',
        'Do you want to restore all keyboard and mouse settings '
        'to their default values?':
            'Tüm klavye ve fare ayarları varsayılan değerlerine '
            'döndürülsün mü?',
        '<p>These controls are already used for:</p>'
        '<p>{action}</p>'
        '<p>Do you want to remove the other controls'
        ' to save these ones?</p>':
            '<p>Bu kontroller zaten şunun için kullanılıyor:</p>'
            '<p>{action}</p>'
            '<p>Bunları kaydetmek için diğer kontroller kaldırılsın mı?</p>',
        'Not Configured': 'Ayarlanmamış',
        'No Modifier': 'Değiştirici Yok',
        'Left': 'Sol',
        'Middle': 'Orta',
        'Ctrl': 'Ctrl',
        'Shift': 'Shift',
        'Alt': 'Alt',
        'Meta': 'Meta',
        'Keypad': 'Sayısal Tuş Takımı',
        'Zoom': 'Yakınlaştır',
        'Zoom (alternative)': 'Yakınlaştır (alternatif)',
        'Pan horizontally': 'Yatay kaydır',
        'Pan horizontally (alternative)': 'Yatay kaydır (alternatif)',
        'Pan vertically': 'Dikey kaydır',
        'Pan vertically (alternative)': 'Dikey kaydır (alternatif)',
        'Pan': 'Kaydır',
        'Pan (alternative)': 'Kaydır (alternatif)',
        'Move Window': 'Pencereyi Taşı',

        # -- Welcome overlay / help -----------------------------------------
        'Paste or drop images and videos here.':
            'Görselleri ve videoları buraya yapıştırın veya sürükleyin.',
        'Right-click for more options.':
            'Daha fazla seçenek için sağ tıklayın.',
        'Double-click the empty canvas to go full screen.':
            'Tam ekran için boş alana çift tıklayın.',
        'Hold Ctrl+Alt and drag to move the window.':
            'Pencereyi taşımak için Ctrl+Alt basılı tutup sürükleyin.',
        'Recent Files': 'Son Dosyalar',
        '&Controls': '&Kontroller',
    },
}


class _LanguageEvents(QtCore.QObject):
    """Emits when the interface language changed."""

    changed = QtCore.pyqtSignal(str)


language_events = _LanguageEvents()

_language = DEFAULT_LANGUAGE


def current_language():
    """The active language code (``en`` or ``tr``)."""

    return _language


def system_language():
    """The language to use when nothing has been chosen yet.

    Turkish systems start in Turkish, everything else in English.
    """

    try:
        code = QtCore.QLocale.system().name()[:2].lower()
    except Exception:  # noqa: BLE001 - locale may be unavailable
        return DEFAULT_LANGUAGE
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def available_languages():
    """Language code -> display name, in menu order."""

    return dict(LANGUAGES)


def set_language(code, notify=True):
    """Activates the given language; returns the code that was set.

    Unknown or empty codes fall back to the default language.
    """

    global _language
    code = (code or '').strip().lower()
    if code not in LANGUAGES:
        code = DEFAULT_LANGUAGE
    changed = code != _language
    _language = code
    logger.info(f'Interface language: {LANGUAGES[code]} ({code})')
    if changed and notify:
        language_events.changed.emit(code)
    return code


def tr(text, *args, **kwargs):
    """Translates ``text`` into the active language.

    ``args``/``kwargs`` are applied with :meth:`str.format` afterwards, so
    translations can reorder placeholders.
    """

    if not text:
        return text
    table = TRANSLATIONS.get(_language)
    translated = table.get(text, text) if table else text
    if args or kwargs:
        try:
            return translated.format(*args, **kwargs)
        except (KeyError, IndexError, ValueError):
            logger.info(f'Bad placeholders in translation: {translated!r}')
            return translated
    return translated
