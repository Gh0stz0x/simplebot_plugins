
import io
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import zipfile
import zlib
from urllib.parse import quote, quote_plus, unquote_plus

import bs4
import requests
from deltachat import Message
from html2text import html2text
from readability import Document
from simplebot import DeltaBot
from simplebot.bot import Replies
from simplebot.commands import IncomingCommand
from simplebot.hookspec import deltabot_hookimpl

__version__ = '1.0.0'
zlib.Z_DEFAULT_COMPRESSION = 9
ua = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:60.0) Gecko/20100101'
ua += ' Firefox/60.0'
HEADERS = {'user-agent': ua}
dbot: DeltaBot
img_providers: list


class FileTooBig(ValueError):
    pass


# ======== Hooks ===============

@deltabot_hookimpl
def deltabot_init(bot: DeltaBot) -> None:
    global dbot, img_providers
    dbot = bot
    img_providers = [_dogpile_imgs, _startpage_imgs, _google_imgs]

    getdefault('max_size', 1024*1024*5)

    bot.filters.register(name=__name__, func=filter_messages)

    bot.commands.register('/ddg', cmd_ddg)
    bot.commands.register('/wt', cmd_wt)
    bot.commands.register('/w', cmd_w)
    bot.commands.register('/wttr', cmd_wttr)
    bot.commands.register('/web', cmd_web)
    bot.commands.register('/read', cmd_read)
    bot.commands.register('/img', cmd_img)
    bot.commands.register('/img1', cmd_img1)
    bot.commands.register('/img5', cmd_img5)
    bot.commands.register('/lyrics', cmd_lyrics)


# ======== Filters ===============

def filter_messages(message: Message, replies: Replies) -> None:
    """Process messages containing URLs.
    """
    match = re.search('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', message.text)
    if not match:
        return
    kwargs = dict(quote=message)
    url = match.group()
    nitter = getdefault('nitter_instance', 'https://nitter.cc')
    if url.startswith('https://twitter.com/'):
        url = url.replace('https://twitter.com', nitter, count=1)
    elif url.startswith('https://mobile.twitter.com/'):
        url = url.replace('https://mobile.twitter.com/', nitter, count=1)
    with requests.get(url, headers=HEADERS, stream=True) as r:
        r.raise_for_status()
        content_type = r.headers.get('content-type', '').lower()
        if 'text/html' in content_type:
            soup = bs4.BeautifulSoup(r.text, 'html5lib')
            [t.extract() for t in soup('script')]
            kwargs['text'] = (soup.title and soup.title.get_text().strip()) or 'Page without title'
            url = r.url
            index = url.find('/', 8)
            if index == -1:
                root = url
            else:
                root = url[:index]
                url = url.rsplit('/', 1)[0]
            tags = (
                ('a', 'href', 'mailto:'),
                ('img', 'src', 'data:'),
                ('source', 'src', 'data:'),
                ('link', 'href', None),
            )
            for tag, attr, iprefix in tags:
                for e in soup(tag, attrs={attr: True}):
                    if iprefix and e[attr].startswith(iprefix):
                        continue
                    e[attr] = re.sub(r'^(//.*)', r'{}:\1'.format(
                        root.split(':', 1)[0]), e[attr])
                    e[attr] = re.sub(
                        r'^(/.*)', r'{}\1'.format(root), e[attr])
                    if not re.match(r'^https?://', e[attr]):
                        e[attr] = '{}/{}'.format(url, e[attr])
            kwargs['html'] = str(soup)
        elif 'image/' in content_type:
            kwargs['filename'] = 'image.' + re.search('image/(\w+)', content_type).group(1)
            kwargs['bytefile'] = io.BytesIO(r.content)
        else:
            size = r.headers.get('content-size')
            if not size:
                size = 0
                max_size = 1024*1024
                for chunk in r.iter_content(chunk_size=102400):
                    size += len(chunk)
                    if size > max_size:
                        size = '>1MB'
                        break
                else:
                    size = '{:,}'.format(size)
            ctype = r.headers.get('content-type', '').split(';')[0] or '-'
            kwargs['text'] = 'Content Type: {}\nContent Size: {}'.format(ctype, size)

    replies.add(**kwargs)


# ======== Commands ===============

def cmd_ddg(command: IncomingCommand, replies: Replies) -> None:
    """Search in DuckDuckGo.
    """
    mode = get_mode(command.message.get_sender_contact().addr)
    page = 'lite' if mode == 'htmlzip' else 'html'
    url = "https://duckduckgo.com/{}?q={}".format(
        page, quote_plus(command.payload))
    replies.add(**download_file(url, mode))


def cmd_wt(command: IncomingCommand, replies: Replies) -> None:
    """Search in Wiktionary.
    """
    sender = command.message.get_sender_contact().addr
    lang = get_locale(sender)
    url = "https://{}.m.wiktionary.org/wiki/?search={}".format(
        lang, quote_plus(command.payload))
    replies.add(**download_file(url, get_mode(sender)))


def cmd_w(command: IncomingCommand, replies: Replies) -> None:
    """Search in Wikipedia.
    """
    sender = command.message.get_sender_contact().addr
    lang = get_locale(sender)
    url = "https://{}.m.wikipedia.org/wiki/?search={}".format(
        lang, quote_plus(command.payload))
    replies.add(**download_file(url, get_mode(sender)))


def cmd_wttr(command: IncomingCommand, replies: Replies) -> None:
    """Search weather info from wttr.in
    """
    lang = get_locale(command.message.get_sender_contact().addr)
    url = 'https://wttr.in/{}_Fnp_lang={}.png'.format(
        quote(command.payload), lang)
    reply = download_file(url)
    reply.pop('text')
    replies.add(**reply)


def cmd_web(command: IncomingCommand, replies: Replies) -> None:
    """Download a webpage or file.
    """
    def download(cmd):
        mode = get_mode(cmd.message.get_sender_contact().addr)
        try:
            d = download_file(cmd.payload, mode)
            text = d.get('text')
            filename = d.get('filename')
            bytefile = d.get('bytefile')
            tempdir = tempfile.mkdtemp() if bytefile else None
            try:
                if bytefile:
                    filename = os.path.join(tempdir, filename)
                    with open(filename, "wb") as f:
                        f.write(bytefile.read())
                if filename:
                    view_type = "file"
                else:
                    view_type = "text"
                msg = Message.new_empty(cmd.bot.account, view_type)
                if text is not None:
                    msg.set_text(text)
                if filename is not None:
                    msg.set_file(filename)
                msg = cmd.message.chat.send_msg(msg)
                cmd.bot.logger.info(
                    "reply id={} chat={} sent with text: {!r}".format(
                        msg.id, msg.chat, msg.text[:50]))
            finally:
                if tempdir:
                    shutil.rmtree(tempdir)
        except FileTooBig as err:
            cmd.message.chat.send_text(str(err))

    threading.Thread(target=download, args=(command,), daemon=True).start()


def cmd_read(command: IncomingCommand, replies: Replies) -> None:
    """Download a webpage and try to improve its readability.
    """
    mode = get_mode(command.message.get_sender_contact().addr)
    try:
        replies.add(**download_file(command.payload, mode, True))
    except FileTooBig as err:
        replies.add(text=str(err))


def cmd_img(command: IncomingCommand, replies: Replies) -> None:
    """Search for images, returns image links.
    """
    text = '\n\n'.join(get_images(command.payload))
    if text:
        replies.add(text='{}:\n\n{}'.format(command.payload, text))
    else:
        replies.add(text='No results for: {}'.format(command.payload))


def cmd_img1(command: IncomingCommand, replies: Replies) -> None:
    """Get an image based on the given text.
    """
    imgs = download_images(command.payload, 1)
    if not imgs:
        replies.add(text='No results for: {}'.format(command.payload))
    else:
        for reply in imgs:
            replies.add(**reply)


def cmd_img5(command: IncomingCommand, replies: Replies) -> None:
    """Search for images, returns 5 results.
    """
    imgs = download_images(command.payload, 5)
    if not imgs:
        replies.add(text='No results for: {}'.format(command.payload))
    else:
        for reply in imgs:
            replies.add(**reply)


def cmd_lyrics(command: IncomingCommand, replies: Replies) -> None:
    """Get song lyrics.
    """
    base_url = 'https://www.lyrics.com'
    url = "{}/lyrics/{}".format(base_url, quote(command.payload))
    with requests.get(url, headers=HEADERS) as r:
        r.raise_for_status()
        soup = bs4.BeautifulSoup(r.text, 'html.parser')
    best_matches = soup.find('div', class_='best-matches')
    a = best_matches and best_matches.a
    if not a:
        soup = soup.find('div', class_='sec-lyric')
        a = soup and soup.a
    if a:
        artist, name = map(unquote_plus, a['href'].split('/')[-2:])
        url = base_url + a['href']
        with requests.get(url, headers=HEADERS) as r:
            r.raise_for_status()
            soup = bs4.BeautifulSoup(r.text, 'html.parser')
            lyric = soup.find(id='lyric-body-text')
            if lyric:
                text = '🎵 {} - {}\n\n{}'.format(name, artist, lyric.get_text())
                replies.add(text=text)
                return

    replies.add(text='No results for: {}'.format(command.payload))


# ======== Utilities ===============

def getdefault(key: str, value=None) -> str:
    val = dbot.get(key, scope=__name__)
    if val is None and value is not None:
        dbot.set(key, value, scope=__name__)
        val = value
    return val


def get_locale(addr: str) -> str:
    return dbot.get('locale', scope=addr) or dbot.get('locale') or 'en'


def get_mode(addr: str) -> str:
    return dbot.get('mode', scope=addr) or dbot.get('mode') or 'htmlzip'


def html2read(html) -> str:
    return Document(html).summary()


def download_images(query: str, img_count: int) -> list:
    imgs = get_images(query)
    results = []
    for img_url in imgs[:img_count]:
        with requests.get(img_url, headers=HEADERS) as r:
            r.raise_for_status()
            filename = 'web' + (get_ext(r) or '.jpg')
            results.append(
                dict(filename=filename, bytefile=io.BytesIO(r.content)))
    return results


def get_images(query: str) -> list:
    for provider in img_providers.copy():
        try:
            dbot.logger.debug('Trying %s', provider)
            imgs = provider(query)
            if imgs:
                return imgs
        except Exception as err:
            img_providers.remove(provider)
            img_providers.append(provider)
            dbot.logger.exception(err)
    return []


def _google_imgs(query: str) -> list:
    url = 'https://www.google.com/search?tbm=isch&sout=1&q={}'.format(
        quote_plus(query))
    with requests.get(url) as r:
        r.raise_for_status()
        soup = bs4.BeautifulSoup(r.text, 'html.parser')
    imgs = []
    for table in soup('table'):
        for img in table('img'):
            imgs.append(img['src'])
    return imgs


def _startpage_imgs(query: str) -> list:
    url = 'https://startpage.com/do/search?cat=pics&cmd=process_search&query={}'.format(quote_plus(query))
    with requests.get(url, headers=HEADERS) as r:
        r.raise_for_status()
        soup = bs4.BeautifulSoup(r.text, 'html.parser')
        r.url
    soup = soup.find('div', class_='mainline-results')
    if not soup:
        return []
    index = url.find('/', 8)
    if index == -1:
        root = url
    else:
        root = url[:index]
        url = url.rsplit('/', 1)[0]
    imgs = []
    for div in soup('div', {'data-md-thumbnail-url': True}):
        img = div['data-md-thumbnail-url']
        if img.startswith('data:'):
            continue
        img = re.sub(
            r'^(//.*)', r'{}:\1'.format(root.split(':', 1)[0]), img)
        img = re.sub(r'^(/.*)', r'{}\1'.format(root), img)
        if not re.match(r'^https?://', img):
            img = '{}/{}'.format(url, img)
        imgs.append(img)
    return imgs


def _dogpile_imgs(query: str) -> list:
    url = 'https://www.dogpile.com/search/images?q={}'.format(
        quote_plus(query))
    with requests.get(url, headers=HEADERS) as r:
        r.raise_for_status()
        soup = bs4.BeautifulSoup(r.text, 'html.parser')
    soup = soup.find('div', class_='mainline-results')
    if not soup:
        return []
    return [img['src'] for img in soup('img')]


def process_html(r) -> str:
    html, url = r.text, r.url
    soup = bs4.BeautifulSoup(html, 'html5lib')
    [t.extract() for t in soup(
        ['script', 'iframe', 'noscript', 'link', 'meta'])]
    soup.head.append(soup.new_tag('meta', charset='utf-8'))
    [comment.extract() for comment in soup.find_all(
        text=lambda text: isinstance(text, bs4.Comment))]
    for b in soup(['button', 'input']):
        if b.has_attr('type') and b['type'] == 'hidden':
            b.extract()
        b.attrs['disabled'] = None
    for i in soup(['i', 'em', 'strong']):
        if not i.get_text().strip():
            i.extract()
    for f in soup('form'):
        del f['action'], f['method']
    for t in soup(['img']):
        src = t.get('src')
        if not src:
            t.extract()
        elif not src.startswith('data:'):
            t.name = 'a'
            t['href'] = src
            alt = t.get('alt')
            if not alt:
                alt = 'IMAGE'
            t.string = '[{}]'.format(alt)
            del t['src'], t['alt']

            parent = t.find_parent('a')
            if parent:
                t.extract()
                parent.insert_before(t)
                contents = [e for e in parent.contents if not isinstance(
                    e, str) or e.strip()]
                if not contents:
                    parent.string = '(LINK)'
    styles = [str(s) for s in soup.find_all('style')]
    for t in soup(lambda t: t.has_attr('class') or t.has_attr('id')):
        classes = []
        for c in t.get('class', []):
            for s in styles:
                if '.'+c in s:
                    classes.append(c)
                    break
        del t['class']
        if classes:
            t['class'] = ' '.join(classes)
        if t.get('id') is not None:
            for s in styles:
                if '#'+t['id'] in s:
                    break
            else:
                del t['id']
    if url.startswith('https://www.startpage.com'):
        for a in soup('a', href=True):
            u = a['href'].split(
                'startpage.com/cgi-bin/serveimage?url=')
            if len(u) == 2:
                a['href'] = unquote_plus(u[1])

    index = url.find('/', 8)
    if index == -1:
        root = url
    else:
        root = url[:index]
        url = url.rsplit('/', 1)[0]
    for a in soup('a', href=True):
        if not a['href'].startswith('mailto:'):
            a['href'] = re.sub(
                r'^(//.*)', r'{}:\1'.format(root.split(':', 1)[0]), a['href'])
            a['href'] = re.sub(
                r'^(/.*)', r'{}\1'.format(root), a['href'])
            if not re.match(r'^https?://', a['href']):
                a['href'] = '{}/{}'.format(url, a['href'])
            a['href'] = 'mailto:{}?body=/web%20{}'.format(
                dbot.self_contact.addr, quote_plus(a['href']))
    return str(soup)


def process_file(r) -> tuple:
    max_size = int(getdefault('max_size'))
    data = b''
    size = 0
    for chunk in r.iter_content(chunk_size=10240):
        data += chunk
        size += len(chunk)
        if size > max_size:
            msg = 'Only files smaller than {} Bytes are allowed'
            raise FileTooBig(msg.format(max_size))

    return (data, get_ext(r))


def get_ext(r) -> str:
    d = r.headers.get('content-disposition')
    if d is not None and re.findall("filename=(.+)", d):
        fname = re.findall(
            "filename=(.+)", d)[0].strip('"')
    else:
        fname = r.url.split('/')[-1].split('?')[0].split('#')[0]
    if '.' in fname:
        ext = '.' + fname.rsplit('.', maxsplit=1)[-1]
    else:
        ctype = r.headers.get(
            'content-type', '').split(';')[0].strip().lower()
        if 'text/plain' == ctype:
            ext = '.txt'
        elif 'image/jpeg' == ctype:
            ext = '.jpg'
        else:
            ext = mimetypes.guess_extension(ctype)
    return ext


def save_file(data, ext: str) -> str:
    fd, path = tempfile.mkstemp(prefix='web-', suffix=ext)
    if isinstance(data, str):
        mode = 'w'
    else:
        mode = 'wb'
    with open(fd, mode) as f:
        f.write(data)
    return path


def save_htmlzip(html) -> str:
    fd, path = tempfile.mkstemp(prefix='web-', suffix='.html.zip')
    with open(fd, 'wb') as f:
        with zipfile.ZipFile(f, 'w', compression=zipfile.ZIP_DEFLATED) as fzip:
            fzip.writestr('index.html', html)
    return path


def download_file(url: str, mode: str = 'htmlzip',
                  readability: bool = False) -> dict:
    if '://' not in url:
        url = 'http://'+url
    with requests.get(url, headers=HEADERS, stream=True) as r:
        r.raise_for_status()
        r.encoding = 'utf-8'
        dbot.logger.debug(
            'Content type: {}'.format(r.headers['content-type']))
        if 'text/html' in r.headers['content-type']:
            if mode == 'text':
                html = html2read(r.text) if readability else r.text
                return dict(text=html2text(html))
            html = process_html(r)
            if readability:
                html = html2read(html)
            if mode == 'md':
                return dict(text=r.url,
                            filename=save_file(html2text(html), '.md'))
            if mode == 'html':
                return dict(text=r.url,
                            filename=save_file(html, '.html'))
            return dict(text=r.url, filename=save_htmlzip(html))
        data, ext = process_file(r)
        return dict(text=r.url, filename='web'+(ext or ''),
                    bytefile=io.BytesIO(data))
