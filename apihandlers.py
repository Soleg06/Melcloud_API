#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import os
from collections import deque

import aiofiles
import arrow
import structlog
import ujson
import aiohttp
# import oauthlib.oauth1
from yarl import URL


class APISessionHandler:
    log = structlog.get_logger(__name__)

    TIME_ZONE = "Europe/Stockholm"
    DATE_FORMAT = "YYYY-MM-DD HH:mm:ss"

    # _instances = {}

    def __init__(self):
        pass

    def __init__(self, name, tokenFileName, lastSessionFileName, headers, RETRIES, RETRY_DELAY, THROTTLE_DELAY, THROTTLE_ERROR_DELAY, loginUrls, MAX_CALLS=None, TIMEFRAME_MAX_CALLS=None, logoutUrls=None, BASE_URL=None, refreshUrls=None, data=None, auth=None, commonSession=None):
        self.name = name
        self.tokenFileName = tokenFileName
        self.lastSessionFileName = lastSessionFileName
        self.headers = headers
        self.data = data
        self.RETRIES = RETRIES
        self.RETRY_DELAY = RETRY_DELAY
        self.THROTTLE_DELAY = THROTTLE_DELAY
        self.THROTTLE_ERROR_DELAY = THROTTLE_ERROR_DELAY
        self.MAX_CALLS = MAX_CALLS
        self.TIMEFRAME_MAX_CALLS = TIMEFRAME_MAX_CALLS
        self.loginUrls = loginUrls or []
        self.logoutUrls = logoutUrls or []
        # self.BASE_URL = BASE_URL
        self.BASE_URL = URL(BASE_URL) if BASE_URL else None
        self.refreshUrls = refreshUrls or []
        self.auth = auth
        self.commonSession = commonSession

        self.doSessionLock = asyncio.Lock()
        self.loginLock = asyncio.Lock()
        self.validateLock = asyncio.Lock()
        self.fileLock = asyncio.Lock()

        self.tokenExpires = None
        self.refreshTokenExpires = None
        self.lastWorkingUrl = None
        self.session = None
        self.callTimes = deque()

    @classmethod
    async def create(cls, *args, **params):
        try:
            # if cls not in cls._instances:
            instance = cls(*args, **params)
            # cls._instances[cls] = instance
            # instance.session = ClientSession(base_url=instance.BASE_URL) if instance.BASE_URL else ClientSession()
            # instance._session = params.pop("commonSession", None)
            # instance.session = await instance._init_session()
            await instance._initSession()
            # return cls._instances[cls]
            return instance

        except Exception as e:
            cls.log.error(f"Exception in create", error=e)

    '''
    async def create(self, name, tokenFileName, lastSessionFileName, headers, RETRIES, RETRY_DELAY, THROTTLE_DELAY, THROTTLE_ERROR_DELAY, loginUrls, logoutUrls=None, BASE_URL=None, refreshUrls=None, data=None, auth=None):
        try:
            self.name = name
            self.tokenFileName = tokenFileName
            self.lastSessionFileName = lastSessionFileName
            self.headers = headers
            self.data = data
            self.RETRIES = RETRIES
            self.RETRY_DELAY = RETRY_DELAY
            self.THROTTLE_DELAY = THROTTLE_DELAY
            self.THROTTLE_ERROR_DELAY = THROTTLE_ERROR_DELAY
            self.loginUrls = loginUrls or []
            self.logoutUrls = logoutUrls or []
            self.BASE_URL = BASE_URL
            self.refreshUrls = refreshUrls or []
            self.auth = auth

            self.doSessionLock = asyncio.Lock()
            self.loginLock = asyncio.Lock()
            self.validateLock = asyncio.Lock()

            self.tokenExpires = None
            self.refreshTokenExpires = None
            self.lastWorkingUrl = None

            # if cls not in cls._instances:
            # cls._instances[cls] = instance
            self.session = ClientSession(base_url=self.BASE_URL) if self.BASE_URL else ClientSession()
            # return cls._instances[cls]
            return self

        except Exception as e:
            self.log.error(f"Exception in create", error=e)
    '''

    async def internetUP(self, retries=5, delay=5):
        out = False
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as _session:
                    async with _session.get('http://google.com') as resp:
                        if resp.status == 200:
                            self.log.info("Internet connection is up")
                            out = True

                return out

            except aiohttp.ClientConnectionError:
                self.log.warning(f"Attempt {attempt + 1}/{retries} failed; retrying in {delay} seconds...")
                await asyncio.sleep(delay)

        self.log.error("Failed to create session: network is unavailable.")

    async def _initSession(self):
        try:
            if self.session is None or self.session.closed:
                if await self.internetUP():
                    self.session = self.commonSession if self.commonSession is not None else aiohttp.ClientSession()

        except Exception as e:
            self.log.error(f"Exception in _init_session", error=e)

    async def closeSession(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def localDoLogin(self, internalCall, skipThrottle=True):
        pass

    async def localDoLogout(self, skipThrottle=True):
        await self.session.close()

    async def localDoRefresh(self, internalCall, skipThrottle=True):
        pass

    async def localSetToken(self, token):
        pass

    async def localUrlPoolCheck(self, result):
        pass

    async def localPreDoSession(self, param):
        pass

    async def doSession(self, internalCall=False, skipThrottle=False, **kwargs):

        async def _writeSessionFile(url, status, text):
            try:
                _now = arrow.now(self.TIME_ZONE)

                if self.MAX_CALLS and self.TIMEFRAME_MAX_CALLS:
                    self.callTimes.append(_now)
                    # Remove timestamps that are outside the current timeframe
                    # while self.callTimes and (_now - self.callTimes[0]).total_seconds() > self.TIMEFRAME_MAX_CALLS:
                    #    self.callTimes.popleft()

                    await self._writeFileAsync(self.lastSessionFileName, {"lastSessionTime": _now.format(self.DATE_FORMAT),
                                                                          "lastStatus": status,
                                                                          "lastUrl": url,
                                                                          "lastText": text,
                                                                          "callTimes": [ts.format(self.DATE_FORMAT) for ts in self.callTimes or []]})
                else:
                    await self._writeFileAsync(self.lastSessionFileName, {"lastSessionTime": _now.format(self.DATE_FORMAT),
                                                                          "lastStatus": status,
                                                                          "lastUrl": url,
                                                                          "lastText": text})

            except Exception as e:
                self.log.error(f"Exception in _writeSessionFile", error=e)

        async def _waitForThrottle():
            try:
                _now = arrow.now(self.TIME_ZONE)
                if self.lastSessionFileName:
                    lastSessionData = await self._readFileAsync(self.lastSessionFileName)
                    if lastSessionData:
                        if self.MAX_CALLS and self.TIMEFRAME_MAX_CALLS:
                            self.callTimes = deque([arrow.get(ts, tzinfo=self.TIME_ZONE) for ts in lastSessionData.get("callTimes", [])])
                            # Remove timestamps that are outside the current timeframe
                            while self.callTimes and (_now - self.callTimes[0]).total_seconds() > self.TIMEFRAME_MAX_CALLS:
                                self.callTimes.popleft()

                            # Check if the number of calls exceeds the maximum allowed
                            if len(self.callTimes) >= self.MAX_CALLS:
                                nextCallTime = self.callTimes[0].shift(seconds=self.TIMEFRAME_MAX_CALLS)
                                delaySeconds = (nextCallTime - _now).total_seconds()
                                self.log.info(f"{self.name} waiting {int(delaySeconds)} seconds due to rate limiting", lencallTimes=len(self.callTimes))
                                await asyncio.sleep(delaySeconds)
                                # self.callTimes.clear()

                        elif self.THROTTLE_DELAY > 0:
                            lastSessionTime = arrow.get(lastSessionData.get("lastSessionTime"), tzinfo=self.TIME_ZONE)
                            lastStatus = lastSessionData.get("lastStatus")
                            delay = self.THROTTLE_ERROR_DELAY if lastStatus == 429 else self.THROTTLE_DELAY
                            nextCallTime = lastSessionTime.shift(seconds=delay)
                            if nextCallTime > _now:
                                delaySeconds = (nextCallTime - _now).total_seconds()
                                self.log.info(f"{self.name} waiting {int(delaySeconds)} seconds before next call")
                                await asyncio.sleep(delaySeconds)

                    else:
                        self.log.warning(f"{self.name} lastsessionfile damaged or missing")

            except Exception as e:
                self.log.error(f"Exception in _waitForThrottle", error=e)

        async def _innerDoSession():
            nonlocal kwargs
            for attempt in range(self.RETRIES):
                try:
                    if not skipThrottle:
                        await _waitForThrottle()
                        if not await self._tokenValid():
                            if not await self.login(internalCall=True):
                                return None

                    for index, url in enumerate(_urls):
                        kwargs["url"] = self.BASE_URL.join(URL(url)) if self.BASE_URL is not None else URL(url)
                        kwargs["headers"] = self.headers
                        newKwargs = await self.localPreDoSession(kwargs)
                        kwargs = newKwargs if newKwargs is not None else kwargs
                        self.log.debug(f"{self.name} preforming request to {kwargs.get('url')}")
                        # Ensure shared session is initialized
                        await self._initSession()
                        async with self.session.request(**kwargs) as response:
                            if 200 <= response.status < 300:
                                content_type = response.headers.get('Content-Type', '').lower()
                                if 'application/json' in content_type:
                                    result = await response.json()
                                    await _writeSessionFile(kwargs.get('url').human_repr(), response.status, ujson.dumps(result))
                                    if not _urlPool or self.localUrlPoolCheck(result):
                                        self.lastWorkingUrl = url
                                        return result
                                    if index == len(_urls) - 1:  # last item
                                        self.log.warning(f"{self.name} failed with urlPool attempt {attempt+1}, retrying in {self.RETRY_DELAY} seconds...")
                                        await asyncio.sleep(self.RETRY_DELAY)
                                else:
                                    self.log.error(f"{self.name} received unexpected content type: {content_type}. Expected 'application/json'. Response text: {await response.text()}")
                                    await _writeSessionFile(kwargs.get('url').human_repr(), response.status, await response.text())
                                    if index == len(_urls) - 1:
                                        await asyncio.sleep(self.RETRY_DELAY)

                            elif response.status == 401:
                                self.log.warning(f"{self.name} 401 unauthorized attempt {attempt+1}")
                                await _writeSessionFile(kwargs.get('url').human_repr(), response.status, await response.text())
                                if not self.loginLock.locked():
                                    if not await self.login(internalCall=True, forceLogin=True):
                                        return None
                                    self.log.warning(f"{self.name} retrying request attempt {attempt+1} in {self.RETRY_DELAY} seconds...")
                                    await asyncio.sleep(self.RETRY_DELAY)
                                    break

                            elif response.status == 404:
                                self.log.error(f"{self.name} 404 not found attempt {attempt+1}")
                                await _writeSessionFile(kwargs.get('url').human_repr(), response.status, await response.text())
                                return

                            elif response.status == 429:
                                await _writeSessionFile(kwargs.get('url').human_repr(), response.status, await response.text())
                                self.log.warning(f"{self.name} 429 too many requests attempt {attempt+1}, retrying after {self.RETRY_DELAY} seconds...", callTimes=self.callTimes)
                                await asyncio.sleep(self.RETRY_DELAY)
                                break

                            else:
                                self.log.error(f"{self.name} request failed with status {response.status} attempt {attempt+1} retrying in {self.RETRY_DELAY} seconds...", url=kwargs.get('url'), params=kwargs.get("params"))
                                await _writeSessionFile(kwargs.get('url').human_repr(), response.status, await response.text())
                                await asyncio.sleep(self.RETRY_DELAY)

                except aiohttp.ClientConnectionError as e:
                    _delay = min(self.RETRY_DELAY * (2 ** attempt), self.RETRY_DELAY * (2 ** self.RETRIES))
                    _status = response.status if 'response' in locals() else 500  # Default to 500 if response is not defined
                    self.log.error(f"{self.name} ClientConnectionError attempt {attempt+1} retrying in {_delay} seconds...", error=e, url=kwargs.get('url'), params=kwargs.get("params"))
                    await _writeSessionFile(url, _status, f"{type(e).__name__}: {str(e)}")
                    await asyncio.sleep(_delay)
                    # reset sessionen bara och det inte är en gemensam session
                    if self.commonSession is None:
                        await self.closeSession()

                except Exception as e:
                    self.log.error(f"{self.name} Exception in _innerDoSession attempt {attempt+1} retrying in {self.RETRY_DELAY} seconds...", url=kwargs.get('url'), params=kwargs.get("params"))
                    await _writeSessionFile(url, 999, f"{type(e).__name__}: {str(e)}")
                    await asyncio.sleep(self.RETRY_DELAY)

            self.log.error(f"{self.name} _innerDoSession max retries reached")

        _urls = kwargs.pop("url")
        _urls = _urls if isinstance(_urls, list) else [_urls]
        _urlPool = len(_urls) > 1

        if _urlPool and self.lastWorkingUrl:
            if skipThrottle:
                if self.lastWorkingUrl in self.loginUrls:
                    self.loginUrls = self._moveToFront(self.lastWorkingUrl, self.loginUrls)

                elif self.lastWorkingUrl in self.refreshUrls:
                    self.refreshUrls = self._moveToFront(self.lastWorkingUrl, self.refreshUrls)

                # elif self.lastWorkingUrl in self.logoutUrls:
                #    self.logoutUrls = self._moveToFront(self.lastWorkingUrl, self.logoutUrls)

            elif self.lastWorkingUrl in _urls:
                _urls = self._moveToFront(self.lastWorkingUrl, _urls)

        if not internalCall:
            async with self.doSessionLock:
                return await _innerDoSession()
        else:
            return await _innerDoSession()

    async def login(self, internalCall=False, forceLogin=False):
        try:
            async with self.loginLock:
                if not forceLogin and await self._getTokenFromFile():
                    return True

                if self.refreshUrls and await self._tokenValid(self.refreshTokenExpires):
                    self.log.info(f"{self.name} refreshing token")
                    if await self.localDoRefresh(internalCall=internalCall):
                        return True
                else:
                    self.log.info(f"{self.name} has no refreshUrl or refreshtoken expired")

                self.log.info(f"{self.name} performing login")
                if await self.localDoLogin(internalCall=internalCall):
                    return True

        except Exception as e:
            self.log.error(f"Exception in login", error=e)

    async def logout(self):
        await self.localDoLogout()

    async def _tokenValid(self, timecheck=None):
        if self.tokenFileName is not None:
            if timecheck is None:
                timecheck = self.tokenExpires
            now = arrow.now(self.TIME_ZONE)
            async with self.validateLock:
                if timecheck is None or now >= timecheck:
                    return False
        return True

    async def _getTokenFromFile(self):
        try:
            tokenData = await self._readFileAsync(self.tokenFileName)
            if tokenData:
                token = tokenData.get("token")
                self.tokenExpires = arrow.get(tokenData.get("tokenExpires"), tzinfo=self.TIME_ZONE)
                if await self._tokenValid():
                    self.log.info(f"{self.name} setting token from file")
                    self.localSetToken(token)
                    return True
                else:
                    self.log.info(f"{self.name} token has expired")
                    return False
            else:
                self.log.warning(f"{self.name} tokenfile damaged or missing")
                return False

        except Exception as e:
            self.log.error(f"Exception in _getTokenFromFile", error=e)
            return False

    async def _writeTokenToFile(self, token):
        await self._writeFileAsync(self.tokenFileName, {"token": token,
                                                        "tokenExpires": self.tokenExpires.format(self.DATE_FORMAT)})

    @staticmethod
    def _moveToFront(item, lst):
        if not lst or lst[0] == item:
            # Item is already the first item
            return lst

        new_lst = lst.copy()
        new_lst.remove(item)
        new_lst.insert(0, item)
        return new_lst

    async def _readFileAsync(self, filename):
        async with self.fileLock:
            try:
                if os.path.exists(filename):
                    async with aiofiles.open(filename, mode="r", encoding="utf-8") as f:
                        _cont = await f.read()
                        return json.loads(_cont)
                return {}

            except Exception as e:
                self.log.error(f"Exception in _readFileAsync", filename=filename, error=e)
                return {}

    async def _writeFileAsync(self, filename, contents):
        async with self.fileLock:
            try:
                async with aiofiles.open(filename, mode="w", encoding="utf-8") as f:
                    await f.write(json.dumps(contents))

            except Exception as e:
                self.log.error(f"Exception in _writeFileAsync", filename=filename, error=e)


class APIMelcloud(APISessionHandler):

    async def localDoLogin(self, internalCall, skipThrottle=True):
        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="POST", url=self.loginUrls, data=ujson.dumps(self.data))
        if out is not None and 'LoginData' in out and 'ContextKey' in out['LoginData']:
            self.log.info(f"{self.name} login success")
            _token = out['LoginData']['ContextKey']
            self.localSetToken(_token)
            self.tokenExpires = arrow.get(out['LoginData']['Expiry']).to(self.TIME_ZONE)
            await self._writeTokenToFile(_token)
            return True
        else:
            self.log.warning(f"{self.name} login failed no accesstoken in reply")

    def localSetToken(self, token):
        self.headers["X-MitsContextKey"] = token if token else None


class APIFlexitgo(APISessionHandler):

    async def localDoLogin(self, internalCall, skipThrottle=True):
        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="POST", url=self.loginUrls, data=self.data)
        if out is not None and 'access_token' in out:
            self.log.info(f"{self.name} login success")
            _token = f"Bearer {out['access_token']}"
            self.localSetToken(_token)
            fmt = "ddd, DD MMM YYYY HH:mm:ss ZZZ"
            self.tokenExpires = arrow.get(out[".expires"], fmt).to(self.TIME_ZONE)
            await self._writeTokenToFile(_token)
            return True
        else:
            self.log.warning(f"{self.name} login failed no accesstoken in reply")

    def localSetToken(self, token):
        self.headers["Authorization"] = token if token else None


class APIEnegic(APISessionHandler):

    async def localDoRefresh(self, internalCall, skipThrottle=True):
        data = self.data.copy()
        data["Token"] = self.headers.get("X-Authorization")
        if data["Token"] is None:
            self.log.info(f"{self.name} data['Token'] is None")
            return

        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="PUT", url=self.refreshUrls, data=ujson.dumps(data))
        if out is not None and 'TokenInfo' in out:
            self.log.info(f"{self.name} refresh success")
            _token = out["TokenInfo"]["Token"]
            self.localSetToken(_token)
            self.tokenExpires = arrow.get(out["TokenInfo"]["ValidTo"]).to(self.TIME_ZONE)
            await self._writeTokenToFile(_token)
            # await self._getAccountOverview()
            return True
        else:
            self.log.warning(f"{self.name} refresh failed no accesstoken in reply")

    async def localDoLogin(self, internalCall, skipThrottle=True):
        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="PUT", url=self.loginUrls, data=ujson.dumps(self.data))
        if out is not None and 'TokenInfo' in out:
            self.log.info(f"{self.name} login success")
            _token = out["TokenInfo"]["Token"]
            self.localSetToken(_token)
            self.tokenExpires = arrow.get(out["TokenInfo"]["ValidTo"]).to(self.TIME_ZONE)
            await self._writeTokenToFile(_token)
            return True
        else:
            self.log.warning(f"{self.name} login failed no accesstoken in reply")

    def localSetToken(self, token):
        self.headers["X-Authorization"] = token if token else None


class APIVerisure(APISessionHandler):

    fmt = "ddd, DD-MMM-YYYY HH:mm:ss ZZZ"

    def _parseCookie(self):
        try:
            for cookie in self.session.cookie_jar:
                if cookie.key == "vs-refresh":
                    self.refreshTokenExpires = arrow.get(cookie["expires"], self.fmt).to(self.TIME_ZONE)
                elif cookie.key == "vs-access":
                    self.tokenExpires = arrow.get(cookie["expires"], self.fmt).to(self.TIME_ZONE)
            return True

        except Exception as e:
            self.log.warning(f"{self.name} cookie damaged or missing", error=e)

    async def _getTokenFromFile(self):
        try:
            self.session.cookie_jar.load(self.tokenFileName)
            if self._parseCookie():
                if await self._tokenValid():
                    self.log.info(f"{self.name} setting cookie from file")
                    return True
                else:
                    self.log.info(f"{self.name} cookie has expired")
            else:
                self.log.warning(f"{self.name} cookie damaged")

        except Exception as e:
            self.log.warning(f"{self.name} cookie damaged or missing", error=e)

    def localUrlPoolCheck(self, result):
        if "errors" not in result:
            return True

    async def localDoRefresh(self, internalCall, skipThrottle=True):
        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="POST", url=self.refreshUrls)
        if out is not None and "accessToken" in out:
            self.log.info(f"{self.name} refresh success")
            self._parseCookie()
            self.session.cookie_jar.save(self.tokenFileName)
            return True
        else:
            self.log.warning(f"{self.name} refresh failed no accesstoken in reply")

    async def localDoLogin(self, internalCall, skipThrottle=True):
        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="POST", url=self.loginUrls, auth=self.auth)
        if out is not None and "accessToken" in out:
            self.log.info(f"{self.name} login success")
            self._parseCookie()
            self.session.cookie_jar.save(self.tokenFileName)
            return True
        else:
            self.log.warning(f"{self.name} login failed no accesstoken in reply")

    async def localDoLogout(self, skipThrottle=True):
        await self.doSession(skipThrottle=skipThrottle, method="DELETE", url=self.logoutUrls)
        await self.session.close()


class APITelldusLocal(APISessionHandler):

    async def localDoRefresh(self, internalCall, skipThrottle=True):
        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="GET", url=self.refreshUrls)
        if out is not None and 'token' in out:
            self.log.info(f"{self.name} refresh success")
            _token = out["token"]
            self.localSetToken(_token)
            self.tokenExpires = arrow.get(out["expires"])
            await self._writeTokenToFile(_token)
            return True
        else:
            self.log.warning(f"{self.name} refresh failed no accesstoken in reply")

    async def localDoLogin(self, internalCall, skipThrottle=True):
        out = await self.doSession(internalCall=internalCall, skipThrottle=skipThrottle, method="PUT", url=self.loginUrls, data=ujson.dumps(self.data))
        if out is not None and 'TokenInfo' in out:
            self.log.info(f"{self.name} login success")
            _token = out["token"]
            self.localSetToken(_token)
            self.tokenExpires = arrow.get(out["expires"])
            await self._writeTokenToFile(_token)
            return True
        else:
            self.log.warning(f"{self.name} login failed no accesstoken in reply")

    def localSetToken(self, token):
        self.headers["Authorization"] = f"Bearer {token}" if token else None


class APITelldusLive(APISessionHandler):

    async def localPreDoSession(self, param):
        out = param.copy()
        _url = out.get("url").with_query(out.pop("params")).human_repr() if out.get("params") else out.get("url").human_repr()
        uri, he, body = self.client.sign(uri=_url, body=out.get("data"), headers=out.get("headers"), http_method=out.get("method"))
        out["url"] = URL(uri)
        out["headers"] = he
        out["data"] = body
        return out

    async def localDoLogin(self, internalCall, skipThrottle=True):
        self.tokenExpires = arrow.get("2099-12-31 23:59:59")
        return True


class APIShelly(APISessionHandler):

    async def localDoLogin(self, internalCall, skipThrottle=True):
        self.tokenExpires = arrow.get("2099-12-31 23:59:59")
        return True


class APIOmlet(APISessionHandler):

    async def localDoLogin(self, internalCall, skipThrottle=True):
        self.tokenExpires = arrow.get("2099-12-31 23:59:59")
        return True
    
    def localSetToken(self, token):
        self.headers["Authorization"] = f"Bearer {token}" if token else None
