import base64
import binascii
import datetime
import io
import os
import re
import traceback
from abc import ABC, abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from functools import partial
from tkinter import Tk, Button, ttk, Image, Label, Menu, END, Listbox, Scrollbar, LEFT, Y, \
    SINGLE, BOTH, RIGHT, VERTICAL, Frame, Entry, \
    StringVar, SUNKEN, W, X, NSEW, Grid, Canvas, HORIZONTAL, NW, BOTTOM, BooleanVar, Checkbutton, DISABLED, NORMAL
from urllib.parse import urlparse

import clipboard
import requests
from PIL import Image, ImageTk

DEBUG = False

USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:68.0) Gecko/20100101 Firefox/68.0'

HEADERS = {
    'User-agent': USER_AGENT,
}

OUTPUT = datetime.datetime.now().strftime('%Y.%m.%d')
CACHE = 'cache'

TIMEOUT = (3.05, 9.05)
PAD = 5
IMG_WIDTH = 120
MAIN_IMG_WIDTH = 450
MAX_ERRORS = 5

executor = ThreadPoolExecutor(max_workers=20)

root = Tk()


# https://imgrock.net/plazf3yq1eb2/956624.jpg.html


class MainWindow:

    def __init__(self):
        global root

        self.menu_bar = Menu(root)
        self.menu_bar.add_command(label="Back", command=self.back_in_history)
        self.menu_bar.add_command(label="Forward", command=self.forward_in_history)
        self.menu_bar.add_command(label="Copy gallery", command=self.copy_gallery_url)
        root.config(menu=self.menu_bar)

        self.provider = None
        self.session = None
        self.show_image = False
        self.hist_window = None
        self.original_image = None
        self.original_image_name = None
        self.main_image = None
        self.main_image_orig = None
        self.resized = False
        self.thumb_prefix = None
        self.proxies = None
        self.gallery_url = None
        self.hist_stack = []
        self.fwd_stack = []

        frm_top = Frame(root)
        self.frm_main = ScrollFrame(root)
        frm_status = Frame(root)

        frm_center = Frame(self.frm_main.view_port)
        frm_left = Frame(self.frm_main.view_port)
        frm_right = Frame(self.frm_main.view_port)

        frm_caption = Frame(frm_center)
        frm_image = Frame(frm_center)

        self.btn_prev = LinkButton(self, frm_caption, text="Previous")
        self.btn_prev.link = "prev link"
        self.btn_prev.pack(side=LEFT)

        self.btn_save = Button(frm_caption, text="Save", command=self.save_image)
        self.btn_save.pack(side=LEFT)

        self.btn_next = LinkButton(self, frm_caption, text="Next")
        self.btn_next.link = "next link"
        self.btn_next.pack(side=LEFT)

        self.btn_paste = Button(frm_top, text="Paste", command=self.paste_from_clipboard)
        self.btn_paste.pack(side=LEFT)

        self.btn_update = Button(frm_top, text="Load image", command=self.load_image_from_input)
        self.btn_update.pack(side=LEFT)

        self.cb_url = ttk.Combobox(frm_top, width=100)
        self.cb_url.bind("<FocusIn>", self.focus_callback)
        # self.cb_url.bind("<Button-1>", self.drop_down_callback)
        self.cb_url.bind('<Return>', self.enter_callback)
        self.cb_url.pack(side=LEFT)

        self.use_proxy = BooleanVar()
        self.use_proxy.set(False)
        self.use_proxy.trace('w', self.on_use_proxy_change)

        self.chk_use_proxy = Checkbutton(frm_top, text='Use proxy', variable=self.use_proxy)
        self.chk_use_proxy.pack(side=LEFT)

        self.cb_proxy = ttk.Combobox(frm_top, width=30, state=DISABLED)
        self.cb_proxy.pack(side=LEFT)

        try:
            with open("proxy.txt") as f:
                self.cb_proxy.set(f.readline().strip())
        except BaseException as error:
            print(error)
            traceback.print_exc()

        self.btn_image = Button(frm_image, command=self.resize_image)
        self.btn_image.pack()

        self.left_buttons = self.fill_panel(frm_left)
        self.right_buttons = self.fill_panel(frm_right)

        self.status = StringVar()
        self.status_label = Label(frm_status, bd=1, relief=SUNKEN, anchor=W,
                                  textvariable=self.status)
        self.status_label.pack(side=LEFT, fill=BOTH, expand=1)
        self.status.set('Status Bar')

        root.bind("<FocusIn>", self.focus_callback)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        frm_caption.pack()
        frm_image.pack()

        frm_left.pack(side=LEFT, fill=BOTH, expand=1)
        frm_center.pack(side=LEFT)
        frm_right.pack(side=RIGHT, fill=BOTH, expand=1)

        frm_top.pack()
        self.frm_main.pack(fill=BOTH, expand=1)
        frm_status.pack(fill=X)

    def load_image_from_input(self):
        self.load_image_retry(self.cb_url.get().strip())

    def load_image_retry(self, input_url):
        err_count = 0
        while err_count < MAX_ERRORS:
            if self.load_image(input_url, True):
                break

            err_count += 1

    def load_image(self, input_url, remember):
        self.set_undefined_state()

        self.cb_url.set(input_url)

        self.provider = self.get_provider()
        cache_path = os.path.join(CACHE, self.provider.get_domen())
        if not os.path.exists(cache_path):
            os.mkdir(cache_path)

        proxy = self.cb_proxy.get().strip()
        if self.use_proxy.get() and len(proxy.strip()) > 0:
            self.proxies = {
                "http": "http://" + proxy,
                "https": "https://" + proxy
            }
            with open("proxy.txt", "w") as f:
                f.write(proxy)
        else:
            self.proxies = None

        http_session = requests.Session()
        http_session.headers.update(HEADERS)

        if len(input_url) == 0:
            self.set_undefined_state()
            return False

        ident = self.get_id(input_url)
        if ident is None:
            print("ident is None")
            return False

        input_url = "https://" + self.provider.get_host() + "/" + ident

        root.title(input_url)

        try:
            html = self.get_from_cache(ident)
            if (html is None) or (len(html) == 0):
                html = self.get_final_page(ident, input_url, http_session)

            if (html is None) or (len(html) == 0):
                return False

            html = html.decode('utf-8')

            if not self.render_page(ident, html, http_session):
                return False

            if remember and (input_url is not None):
                if len(self.hist_stack) == 0 or (input_url != self.hist_stack[-1]):
                    self.hist_stack.append(input_url)
                if len(self.fwd_stack) > 0 and (input_url == self.fwd_stack[-1]):
                    self.fwd_stack.pop()
                else:
                    self.fwd_stack.clear()

        except BaseException as error:
            root.after_idle(self.set_undefined_state)
            print("Exception URL: " + input_url)
            print(error)
            traceback.print_exc()
            return False
        finally:
            http_session.close()

        return True

    def get_final_page(self, ident, input_url, http_session):
        response = http_session.get(input_url, proxies=self.proxies, timeout=TIMEOUT)
        if response.status_code == 404:
            print("input_url response.status_code == 404")
            return None

        html = response.content.decode('utf-8')

        if DEBUG:
            with open('1.html', 'w') as f:
                f.write(html)

        # sometimes this functions fails (i don't want to tamper with this)
        redirect_url = self.provider.get_redirect_url(html)
        if redirect_url is not None:
            if len(redirect_url) == 0:
                print("(redirect_url is None) or (len(redirect_url) == 0)")
                return None

            http_session.headers.update({'Referer': input_url})
            response = http_session.get(redirect_url, proxies=self.proxies, timeout=TIMEOUT)
            if response.status_code == 404:
                print("redirect_url response.status_code == 404")
                return None

            html = response.content.decode('utf-8')

            if DEBUG:
                with open('2.html', 'w') as f:
                    f.write(html)

        pos = html.find('File Not Found')
        if pos >= 0:
            print("File Not Found: " + input_url)
            return None

        param = self.provider.get_post_param(html)
        if len(param) == 0:
            print("len(param) == 0")
            return None

        post_fields = {
            'op': 'view',
            'id': ident,
            'pre': 1,
            param: 1
        }
        response = http_session.post(redirect_url, data=post_fields, proxies=self.proxies, timeout=TIMEOUT)
        if response.status_code == 404:
            print("POST: redirect_url response.status_code == 404")
            return None

        html = response.content

        if DEBUG:
            with open('3.html', 'wb') as f:
                f.write(html)

        self.put_to_cache(ident, html)

        return html

    def render_page(self, ident, html, http_session):
        thumb_url = get_thumb(html)
        if len(thumb_url) == 0:
            print("len(thumb_url) == 0")
            return False

        slash_pos = thumb_url.rfind('/')
        self.thumb_prefix = thumb_url[: slash_pos + 1]

        self.gallery_url = search('href="([^"]*)">More from gallery</a>', html)

        self.reconfigure_prev_button(http_session, html)
        self.reconfigure_next_button(http_session, html)

        executor.submit(self.reconfigure_left_buttons, html)
        executor.submit(self.reconfigure_right_buttons, html)

        image_url = self.provider.get_image_url(html)

        fname = get_filename(image_url)
        dot_pos = fname.rfind('.')
        self.original_image_name = fname[: dot_pos] + '_' + ident + fname[dot_pos:]
        self.original_image = self.get_from_cache(self.original_image_name)

        if (self.original_image is None) or (len(self.original_image) == 0):
            response = http_session.get(image_url, proxies=self.proxies, timeout=TIMEOUT)
            if response.status_code == 404:
                print("image_url response.status_code == 404")
                return False

            self.original_image = response.content

            if DEBUG:
                with open(self.original_image_name, 'wb') as f:
                    f.write(self.original_image)

            self.put_to_cache(self.original_image_name, self.original_image)

        img = Image.open(io.BytesIO(self.original_image))
        w, h = img.size
        k = MAIN_IMG_WIDTH / w
        img_resized = img.resize((MAIN_IMG_WIDTH, int(h * k)))

        root.title(f"{root.title()} ({w}x{h})")

        self.resized = True
        self.main_image_orig = ImageTk.PhotoImage(img)
        self.main_image = ImageTk.PhotoImage(img_resized)
        self.btn_image.config(image=self.main_image)

        return True

    def focus_callback(self, event):
        self.cb_url.selection_range(0, END)

    def drop_down_callback(self, event):
        self.cb_url.focus_set()
        self.cb_url.selection_range(0, END)
        self.cb_url.event_generate('<Down>')

    def enter_callback(self, event):
        self.load_image_from_input()

    def on_close(self):
        global root

        root.update_idletasks()
        root.destroy()

    def set_undefined_state(self):
        global root

        self.main_image = None
        self.main_image_orig = None
        self.original_image = None
        self.original_image_name = None
        self.btn_image.config(image=None)
        root.title(None)
        self.btn_prev.config(image=None, command=None)
        self.btn_next.config(image=None, command=None)

    def paste_from_clipboard(self):
        self.cb_url.set(clipboard.paste())
        self.cb_url.selection_range(0, END)

    def save_image(self):
        if self.original_image is None:
            return

        filename = self.original_image_name
        i = 1
        while os.path.exists(os.path.join(OUTPUT, filename)):
            filename, file_extension = os.path.splitext(self.original_image_name)
            filename = f'{filename}_{i:04}{file_extension}'
            i += 1

        with open(os.path.join(OUTPUT, filename), 'wb') as f:
            f.write(self.original_image)

    def on_enter(self, event):
        self.status.set(event.widget.link)

    def on_leave(self, enter):
        self.status.set("")

    def fill_panel(self, panel):
        buttons = []
        for i in range(4):
            Grid.columnconfigure(panel, i, weight=1)
            for j in range(2):
                Grid.rowconfigure(panel, j, weight=1)
                btn = LinkButton(self, panel, text=f"({i}, {j})")
                btn.link = f"({i}, {j})"
                btn.grid(row=i, column=j, sticky=NSEW, padx=PAD, pady=PAD)
                buttons.append(btn)

        return buttons

    def resize_image(self):
        self.btn_image.config(image=(self.main_image_orig if self.resized else self.main_image))
        self.resized = not self.resized
        self.frm_main.scroll_top_left()

    def get_id(self, url):
        found = re.search(r"https?://" + self.provider.get_domen() + r"\.[a-z]+/(.+?)(?:/|$)", url)
        if (found is None) or (found.group(0) is None):
            return None

        return found.group(1)

    def reconfigure_left_buttons(self, html):
        tab = get_more_from_author(html)
        reconfigure_buttons(self, self.left_buttons, tab)

    def reconfigure_right_buttons(self, html):
        tab = get_more_from_gallery(html)
        reconfigure_buttons(self, self.right_buttons, tab)

    def reconfigure_prev_button(self, http_session, html):
        url = get_prev_url(html)
        if len(url) == 0:
            return

        ident = self.get_id(url)
        img_url = self.thumb_prefix + ident + '_t.jpg'
        self.reconfigure_button(http_session, self.btn_prev, url, img_url)

    def reconfigure_next_button(self, http_session, html):
        url = get_next_url(html)
        if len(url) == 0:
            return

        ident = self.get_id(url)
        img_url = self.thumb_prefix + ident + '_t.jpg'
        self.reconfigure_button(http_session, self.btn_next, url, img_url)

    def reconfigure_button(self, http_session, btn, url, img_url):
        btn.link = url
        btn.config(command=partial(self.load_image_retry, url))

        filename = get_filename(img_url)
        image = self.get_from_cache(filename)
        if (image is None) or (len(image) == 0):
            image = download_image(http_session, img_url)
            self.put_to_cache(filename, image)

        img = Image.open(io.BytesIO(image))
        w, h = img.size
        k = IMG_WIDTH / w
        img_resized = img.resize((IMG_WIDTH, int(h * k)))
        photo_image = ImageTk.PhotoImage(img_resized)
        if photo_image is None:
            return

        btn.config(image=photo_image)
        btn.image = photo_image

    def on_use_proxy_change(self, *args):
        if self.use_proxy.get():
            self.cb_proxy.config(state=NORMAL)
            self.cb_proxy.focus_set()
            self.cb_proxy.selection_range(0, END)
        else:
            self.cb_proxy.config(state=DISABLED)

    def get_provider(self):
        input_url = self.cb_url.get()

        pos = input_url.find(ImgRock.DOMEN)
        if pos >= 0:
            return ImgRock()

        pos = input_url.find(ImgView.DOMEN)
        if pos >= 0:
            return ImgView()

        pos = input_url.find(ImgTown.DOMEN)
        if pos >= 0:
            return ImgTown()

        pos = input_url.find(ImgOutlet.DOMEN)
        if pos >= 0:
            return ImgOutlet()

        pos = input_url.find(ImgMaze.DOMEN)
        if pos >= 0:
            return ImgMaze()

        pos = input_url.find(ImgDew.DOMEN)
        if pos >= 0:
            return ImgDew()

        return None

    def copy_gallery_url(self):
        clipboard.copy(self.gallery_url)

    def back_in_history(self):
        if len(self.hist_stack) < 2:
            return

        self.fwd_stack.append(self.hist_stack.pop())

        self.load_image(self.hist_stack[-1], False)

    def forward_in_history(self):
        if len(self.fwd_stack) == 0:
            return

        self.load_image(self.fwd_stack[-1], True)

    def get_from_cache(self, filename):
        full_path = os.path.join(CACHE, self.provider.get_domen(), filename)
        if not os.path.exists(full_path):
            return None

        with open(full_path, 'rb') as f:
            return f.read()

    def put_to_cache(self, filename, data):
        full_path = os.path.join(CACHE, self.provider.get_domen(), filename)

        with open(full_path, 'wb') as f:
            f.write(data)


class ScrollFrame(Frame):
    """Copyright: https://gist.github.com/mp035/9f2027c3ef9172264532fcd6262f3b01"""

    def __init__(self, parent, cnf={}, **kw):
        super().__init__(parent, cnf, **kw)  # create a frame (self)

        self.canvas = Canvas(self, borderwidth=0, background="#ffffff")  # place canvas on self

        # place a frame on the canvas, this frame will hold the child widgets
        self.view_port = Frame(self.canvas, background="#ffffff")

        self.vsb = Scrollbar(self, orient=VERTICAL, command=self.canvas.yview)  # place a scrollbar on self
        self.hsb = Scrollbar(self, orient=HORIZONTAL, command=self.canvas.xview)  # place a scrollbar on self
        # attach scrollbar action to scroll of canvas
        self.canvas.configure(xscrollcommand=self.hsb.set, yscrollcommand=self.vsb.set)

        self.vsb.pack(side=RIGHT, fill=Y)  # pack scrollbar to right of self
        self.hsb.pack(side=BOTTOM, fill=X)  # pack scrollbar to right of self
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)  # pack canvas to left of self and expand to fil
        self.canvas_window = self.canvas.create_window((4, 4), window=self.view_port, anchor=NW,
                                                       # add view port frame to canvas
                                                       tags="self.view_port")

        # bind an event whenever the size of the viewPort frame changes.
        self.view_port.bind("<Configure>", self.on_frame_configure)
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel_y)
        self.canvas.bind_all("<Control-MouseWheel>", self.on_mousewheel_x)

        # perform an initial stretch on render, otherwise the scroll region has a tiny border until the first resize
        self.on_frame_configure(None)

    def on_frame_configure(self, event):
        """Reset the scroll region to encompass the inner frame"""
        # whenever the size of the frame changes, alter the scroll region respectively.
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_mousewheel_x(self, event):
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_mousewheel_y(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def scroll_top_left(self):
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)


class LinkButton(Button):
    def __init__(self, win, parent=None, *args, **kw):
        super().__init__(parent, *args, **kw)
        super().bind("<Enter>", win.on_enter)
        super().bind("<Leave>", win.on_leave)
        super().bind("<Button-3>", self.copy_link)
        self.link = None
        self.image = None

    def copy_link(self, event):
        clipboard.copy(self.link)


def download_image(http_session, url):
    response = http_session.get(url, timeout=TIMEOUT)
    if response.status_code == 404:
        return None

    image = response.content

    if DEBUG:
        with open(get_filename(url), 'wb') as f:
            f.write(image)

    return image


def get_filename(url):
    res = urlparse(url)
    fname = os.path.basename(res.path)

    if fname.endswith(".html"):
        return fname[:-5]

    return fname


def reconfigure_buttons(win, buttons, html):
    http_session = requests.Session()
    http_session.headers.update(HEADERS)

    try:
        i = 0
        for m in re.finditer('<td>.*?href="(.*?)".*?src="(.*?)".*?</td>', html, re.MULTILINE | re.DOTALL):
            win.reconfigure_button(http_session, buttons[i], m.group(1), m.group(2))
            i += 1
    except BaseException as error:
        print(error)
        traceback.print_exc()
        return False
    finally:
        http_session.close()


def search(pattern, string):
    found = re.search(pattern, string, re.MULTILINE | re.DOTALL)
    if (found is None) or (found.group(0) is None):
        return ""

    return found.group(1)


def get_next_url(html):
    return search('< Previous.+?<a style=.+?href="(.*?)"><span.*?>Next', html)


def get_prev_url(html):
    return search('<a style=.+?href="(.*?)"><span.*?>< Previous', html)


def get_more_from_author(html):
    tab = search('<td align="left".*?<table>(.*?)</table>.*?</td>', html)
    return tab


def get_more_from_gallery(html):
    tab = search('<td align="right".*?<table>(.*?)</table>.*?</td>', html)
    return tab


def get_thumb(html):
    return search('\[IMG\](.*?)\[/IMG\]', html)


class AbstractProvider(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def get_host(self):
        pass

    @abstractmethod
    def get_domen(self):
        pass

    @abstractmethod
    def get_redirect_url(self, html):
        pass

    @abstractmethod
    def get_post_param(self, html):
        pass

    @abstractmethod
    def get_image_url(self, html):
        pass


class ImgRock(AbstractProvider):
    DOMEN = "imgrock"

    def __init__(self):
        super().__init__()

    def get_host(self):
        return "imgrock.pw"

    def get_domen(self):
        return ImgRock.DOMEN

    def get_redirect_url(self, html):
        try:
            _0x92afb7 = search(r'_0x92afb7="(.*?)"', html)
            _0x1cdcb3 = search(r'_0x1cdcb3="(.*?)"', html)
            _0x31f1b4 = search(r'_0x31f1b4="(.*?)"', html)
            _0x4817e7 = search(r'_0x4817e7="(.*?)"', html)
            _0x2c6182 = search(r'_0x2c6182="(.*?)"', html)
            _0x53e80d = search(r'_0x53e80d="(.*?)"', html)
            _0x375c1e = search(r'_0x375c1e="(.*?)"', html)
            _0x16777a = search(r'_0x16777a="(.*?)"', html)
            _0x14ff50 = search(r'_0x14ff50="(.*?)"', html)
            _0x18dc18 = search(r'_0x18dc18="(.*?)"', html)

            _0x541840 = _0x53e80d + _0x16777a + _0x92afb7 + _0x31f1b4
            _0x51318f = _0x375c1e + _0x14ff50 + _0x4817e7
            _0x574bee = _0x51318f + _0x541840 + _0x18dc18 + _0x2c6182

            return base64.b64decode(_0x574bee)
        except binascii.Error as ex:
            print(ex)
            traceback.print_exc()
            return ''

    def get_post_param(self, html):
        _0x161539 = search("_0x161539='(.*?)'", html)
        _0xac7006 = search("_0xac7006='(.*?)'", html)

        return _0x161539 + _0xac7006

    def get_image_url(self, html):
        _0xDB36 = search('_0xDB36="(.*?)"', html)
        _0xDB54 = search('_0xDB54="(.*?)"', html)
        return _0xDB36 + '/img/' + _0xDB54


class ImgView(AbstractProvider):
    DOMEN = "imgview"

    def __init__(self):
        super().__init__()

    def get_host(self):
        return "imgview.pw"

    def get_domen(self):
        return ImgView.DOMEN

    def get_redirect_url(self, html):
        try:
            _0x474995 = search(r'_0x474995="(.*?)"', html)
            _0x105bd2 = search(r'_0x105bd2="(.*?)"', html)
            _0x5f000f = search(r'_0x5f000f="(.*?)"', html)
            _0x5f4353 = search(r'_0x5f4353="(.*?)"', html)
            _0x39b490 = search(r'_0x39b490="(.*?)"', html)
            _0x51ca4d = search(r'_0x51ca4d="(.*?)"', html)
            _0x3edc55 = search(r'_0x3edc55="(.*?)"', html)
            _0x2091c4 = search(r'_0x2091c4="(.*?)"', html)
            _0x388eb7 = search(r'_0x388eb7="(.*?)"', html)
            _0x308cf0 = search(r'_0x308cf0="(.*?)"', html)

            _0x33d616 = _0x51ca4d + _0x2091c4 + _0x474995 + _0x5f000f
            _0x1dbdb1 = _0x3edc55 + _0x388eb7 + _0x5f4353
            _0x180c90 = _0x1dbdb1 + _0x33d616 + _0x308cf0 + _0x39b490

            return base64.b64decode(_0x180c90)
        except binascii.Error as ex:
            print(ex)
            traceback.print_exc()
            return ''

    def get_post_param(self, html):
        _0x6f3649 = search("_0x6f3649='(.*?)'", html)
        _0x5754e8 = search("_0x5754e8='(.*?)'", html)
        _0x58bd37 = search("_0x58bd37='(.*?)'", html)
        _0x23f325 = search("_0x23f325='(.*?)'", html)
        _0x3e41de = search("_0x3e41de='(.*?)'", html)
        _0x1728a8 = search("_0x1728a8='(.*?)'", html)
        _0x46dc6a = search("_0x46dc6a='(.*?)'", html)
        _0x2a20de = search("_0x2a20de='(.*?)'", html)
        _0x1a0961 = search("_0x1a0961='(.*?)'", html)
        _0x1008b5 = search("_0x1008b5='(.*?)'", html)
        _0x301249 = search("_0x301249='(.*?)'", html)

        return _0x6f3649 + _0x5754e8 + _0x58bd37 + _0x23f325 + _0x3e41de + _0x1728a8 + _0x46dc6a + _0x2a20de + _0x1a0961 + _0x1008b5 + _0x301249

    def get_image_url(self, html):
        return search(r'>Next.+?<img src="(.*?)" class="picview" alt=', html)


class ImgTown(AbstractProvider):
    DOMEN = "imgtown"

    def __init__(self):
        super().__init__()

    def get_host(self):
        return "imgtown.pw"

    def get_domen(self):
        return ImgTown.DOMEN

    def get_redirect_url(self, html):
        try:
            _0x92afb7 = search(r'_0x92afb7="(.*?)"', html)
            _0x1cdcb3 = search(r'_0x1cdcb3="(.*?)"', html)
            _0x31f1b4 = search(r'_0x31f1b4="(.*?)"', html)
            _0x4817e7 = search(r'_0x4817e7="(.*?)"', html)
            _0x2c6182 = search(r'_0x2c6182="(.*?)"', html)
            _0x53e80d = search(r'_0x53e80d="(.*?)"', html)
            _0x375c1e = search(r'_0x375c1e="(.*?)"', html)
            _0x16777a = search(r'_0x16777a="(.*?)"', html)
            _0x14ff50 = search(r'_0x14ff50="(.*?)"', html)
            _0x18dc18 = search(r'_0x18dc18="(.*?)"', html)

            _0x541840 = _0x53e80d + _0x16777a + _0x92afb7 + _0x31f1b4
            _0x51318f = _0x375c1e + _0x14ff50 + _0x4817e7
            _0x574bee = _0x51318f + _0x541840 + _0x18dc18 + _0x2c6182

            return base64.b64decode(_0x574bee)
        except binascii.Error as ex:
            print(ex)
            traceback.print_exc()
            return ''

    def get_post_param(self, html):
        _0x6f3649 = search("_0x6f3649='(.*?)'", html)
        _0x5754e8 = search("_0x5754e8='(.*?)'", html)
        _0x58bd37 = search("_0x58bd37='(.*?)'", html)
        _0x23f325 = search("_0x23f325='(.*?)'", html)
        _0x3e41de = search("_0x3e41de='(.*?)'", html)
        _0x1728a8 = search("_0x1728a8='(.*?)'", html)
        _0x46dc6a = search("_0x46dc6a='(.*?)'", html)
        _0x2a20de = search("_0x2a20de='(.*?)'", html)
        _0x1a0961 = search("_0x1a0961='(.*?)'", html)
        _0x1008b5 = search("_0x1008b5='(.*?)'", html)
        _0x301249 = search("_0x301249='(.*?)'", html)

        return _0x6f3649 + _0x5754e8 + _0x58bd37 + _0x23f325 + _0x3e41de + _0x1728a8 + _0x46dc6a + _0x2a20de + _0x1a0961 + _0x1008b5 + _0x301249

    def get_image_url(self, html):
        return search(r'>Next.+?<img src="(.*?)" class="picview" alt=', html)


class ImgOutlet(AbstractProvider):
    DOMEN = "imgoutlet"

    def __init__(self):
        super().__init__()

    def get_host(self):
        return "imgoutlet.pw"

    def get_domen(self):
        return ImgOutlet.DOMEN

    def get_redirect_url(self, html):
        try:
            _0x4ae180 = search(r'_0x4ae180="(.*?)"', html)
            _0x31c497 = search(r'_0x31c497="(.*?)"', html)
            _0x580e37 = search(r'_0x580e37="(.*?)"', html)
            _0x337490 = search(r'_0x337490="(.*?)"', html)
            _0x5aa778 = search(r'_0x5aa778="(.*?)"', html)
            _0x4c78db = search(r'_0x4c78db="(.*?)"', html)
            _0x5f2b0 = search(r'_0x5f2b0="(.*?)"', html)
            _0x19792c = search(r'_0x19792c="(.*?)"', html)
            _0x269158 = search(r'_0x269158="(.*?)"', html)
            _0xacf574 = search(r'_0xacf574="(.*?)"', html)

            _0x3ec3bd = _0x4c78db + _0x19792c + _0x4ae180 + _0x580e37
            _0x5051f4 = _0x5f2b0 + _0x269158 + _0x337490
            _0x1587cc = _0x5051f4 + _0x3ec3bd + _0xacf574 + _0x5aa778

            return base64.b64decode(_0x1587cc)
        except binascii.Error as ex:
            print(ex)
            traceback.print_exc()
            return ''

    def get_post_param(self, html):
        _0x161539 = search("_0x161539='(.*?)'", html)
        _0xac7006 = search("_0xac7006='(.*?)'", html)

        return _0x161539 + _0xac7006

    def get_image_url(self, html):
        _0xDB36 = search('_0xDB36="(.*?)"', html)
        _0xDB54 = search('_0xDB54="(.*?)"', html)
        return _0xDB36 + '/img/' + _0xDB54


class ImgMaze(AbstractProvider):
    DOMEN = "imgmaze"

    def __init__(self):
        super().__init__()

    def get_host(self):
        return "imgmaze.pw"

    def get_domen(self):
        return ImgMaze.DOMEN

    def get_redirect_url(self, html):
        try:
            _0x1ab2d2 = search(r'_0x1ab2d2="(.*?)"', html)
            _0x2b3b4c = search(r'_0x2b3b4c="(.*?)"', html)
            _0x3b4d44 = search(r'_0x3b4d44="(.*?)"', html)
            _0x43582a = search(r'_0x43582a="(.*?)"', html)
            _0x501afd = search(r'_0x501afd="(.*?)"', html)
            _0x23d671 = search(r'_0x23d671="(.*?)"', html)
            _0x220856 = search(r'_0x220856="(.*?)"', html)
            _0x473131 = search(r'_0x473131="(.*?)"', html)
            _0x421cf1 = search(r'_0x421cf1="(.*?)"', html)
            _0x86fd3f = search(r'_0x86fd3f="(.*?)"', html)

            _0x15e3ee = _0x23d671 + _0x473131 + _0x1ab2d2 + _0x3b4d44
            _0x5d3c98 = _0x220856 + _0x421cf1 + _0x43582a;
            _0x358455 = _0x5d3c98 + _0x15e3ee + _0x86fd3f + _0x501afd

            return base64.b64decode(_0x358455)
        except binascii.Error as ex:
            print(ex)
            traceback.print_exc()
            return ''

    def get_post_param(self, html):
        _0x6f3649 = search("_0x6f3649='(.*?)'", html)
        _0x5754e8 = search("_0x5754e8='(.*?)'", html)
        _0x58bd37 = search("_0x58bd37='(.*?)'", html)
        _0x23f325 = search("_0x23f325='(.*?)'", html)
        _0x3e41de = search("_0x3e41de='(.*?)'", html)
        _0x1728a8 = search("_0x1728a8='(.*?)'", html)
        _0x46dc6a = search("_0x46dc6a='(.*?)'", html)
        _0x2a20de = search("_0x2a20de='(.*?)'", html)
        _0x1a0961 = search("_0x1a0961='(.*?)'", html)
        _0x1008b5 = search("_0x1008b5='(.*?)'", html)
        _0x301249 = search("_0x301249='(.*?)'", html)

        return _0x6f3649 + _0x5754e8 + _0x58bd37 + _0x23f325 + _0x3e41de + _0x1728a8 + _0x46dc6a + _0x2a20de + _0x1a0961 + _0x1008b5 + _0x301249

    def get_image_url(self, html):
        return search(r'>Next.+?<img src="(.*?)" class="picview" alt=', html)


class ImgDew(AbstractProvider):
    DOMEN = "imgdew"

    def __init__(self):
        super().__init__()

    def get_host(self):
        return "imgdew.pw"

    def get_domen(self):
        return ImgDew.DOMEN

    def get_redirect_url(self, html):
        try:
            _0x474995 = search(r'_0x474995="(.*?)"', html)
            _0x105bd2 = search(r'_0x105bd2="(.*?)"', html)
            _0x5f000f = search(r'_0x5f000f="(.*?)"', html)
            _0x5f4353 = search(r'_0x5f4353="(.*?)"', html)
            _0x39b490 = search(r'_0x39b490="(.*?)"', html)
            _0x51ca4d = search(r'_0x51ca4d="(.*?)"', html)
            _0x3edc55 = search(r'_0x3edc55="(.*?)"', html)
            _0x2091c4 = search(r'_0x2091c4="(.*?)"', html)
            _0x388eb7 = search(r'_0x388eb7="(.*?)"', html)
            _0x308cf0 = search(r'_0x308cf0="(.*?)"', html)

            _0x33d616 = _0x51ca4d + _0x2091c4 + _0x474995 + _0x5f000f
            _0x1dbdb1 = _0x3edc55 + _0x388eb7 + _0x5f4353
            _0x180c90 = _0x1dbdb1 + _0x33d616 + _0x308cf0 + _0x39b490

            return base64.b64decode(_0x180c90)
        except binascii.Error as ex:
            print(ex)
            traceback.print_exc()
            return ''

    def get_post_param(self, html):
        _0x6f3649 = search("_0x6f3649='(.*?)'", html)
        _0x5754e8 = search("_0x5754e8='(.*?)'", html)
        _0x58bd37 = search("_0x58bd37='(.*?)'", html)
        _0x23f325 = search("_0x23f325='(.*?)'", html)
        _0x3e41de = search("_0x3e41de='(.*?)'", html)
        _0x1728a8 = search("_0x1728a8='(.*?)'", html)
        _0x46dc6a = search("_0x46dc6a='(.*?)'", html)
        _0x2a20de = search("_0x2a20de='(.*?)'", html)
        _0x1a0961 = search("_0x1a0961='(.*?)'", html)
        _0x1008b5 = search("_0x1008b5='(.*?)'", html)
        _0x301249 = search("_0x301249='(.*?)'", html)

        return _0x6f3649 + _0x5754e8 + _0x58bd37 + _0x23f325 + _0x3e41de + _0x1728a8 + _0x46dc6a + _0x2a20de + _0x1a0961 + _0x1008b5 + _0x301249

    def get_image_url(self, html):
        return search(r'>Next.+?<img src="(.*?)" class="picview" alt=', html)


class HistoryWindow:

    def __init__(self, parent, win):
        self.window = win
        self.parent_window = parent
        self.window.title("Full history")
        self.window.resizable(False, False)

        frm_top = Frame(win)
        frm_bottom = Frame(win)

        self.search = StringVar()
        self.search.trace("w", lambda name, index, mode, sv=self.search: self.on_search(sv))
        self.entry_search = Entry(frm_top, textvariable=self.search, width=57)
        self.entry_search.pack(side=LEFT, fill=BOTH, expand=1)

        self.btn_clear = Button(frm_top, text="Clear", command=self.on_clear)
        self.btn_clear.pack(side=RIGHT, fill=BOTH, expand=1)

        self.list_box = Listbox(frm_bottom, width=60, height=40, selectmode=SINGLE)
        self.list_box.pack(side=LEFT, fill=BOTH, expand=1)
        scroll = Scrollbar(frm_bottom, command=self.list_box.yview, orient=VERTICAL)
        scroll.pack(side=RIGHT, fill=Y)
        self.list_box.config(yscrollcommand=scroll.set)
        self.list_box.bind('<<ListboxSelect>>', self.on_listbox_select)

        frm_top.pack()
        frm_bottom.pack()

        self.window.bind("<FocusIn>", self.focus_callback)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.fill_list_box()

    def on_clear(self):
        self.search.set("")
        self.on_search(self.search)

    def on_search(self, search):
        query = search.get().strip().lower()
        if len(query) < 2:
            self.fill_list_box()
            return

        self.list_box.delete(0, END)
        search_results = []
        for key in self.parent_window.hist_dict:
            pos = key.lower().find(query)
            if pos == -1:
                continue

            search_results.append((key, pos))

        search_results.sort(key=lambda x: x[1])
        self.list_box.insert(END, *[x[0] for x in search_results])

    def fill_list_box(self):
        self.list_box.delete(0, END)
        hist = sorted(self.parent_window.hist_dict.items(), key=lambda x: x[1], reverse=True)
        self.list_box.insert(END, *[x[0] for x in hist])

    def on_listbox_select(self, event):
        w = event.widget
        selected = w.curselection()
        if len(selected) == 0:
            return

        index = selected[0]
        value = w.get(index)
        self.parent_window.cb_model.set(value)

    def lift(self):
        self.window.lift()

    def on_close(self):
        self.parent_window.hist_window = None
        self.window.update_idletasks()
        self.window.destroy()

    def focus_callback(self, event):
        self.entry_search.selection_range(0, END)
        root.lift()


if __name__ == "__main__":
    if not os.path.exists(OUTPUT):
        os.mkdir(OUTPUT)

    if not os.path.exists(CACHE):
        os.mkdir(CACHE)

    root.geometry("1200x600")
    main_win = MainWindow()
    root.mainloop()
