"""
Handles client connection/disconnection.
"""
import asyncio
import socket
import ssl
from typing import Any, Optional, Type, Union, cast

from .default import Default, _default
from .errors import (
    SMTPConnectError,
    SMTPConnectTimeoutError,
    SMTPResponseException,
    SMTPServerDisconnected,
    SMTPTimeoutError,
)
from .protocol import SMTPProtocol
from .response import SMTPResponse
from .status import SMTPStatus


__all__ = ("SMTPConnection",)


SMTP_PORT = 25
SMTP_TLS_PORT = 465
SMTP_STARTTLS_PORT = 587
DEFAULT_TIMEOUT = 60


class SMTPConnection:
    """
    Handles connection/disconnection from the SMTP server provided.

    Keyword arguments can be provided either on :meth:`__init__` or when
    calling the :meth:`connect` method. Note that in both cases these options
    are saved for later use; subsequent calls to :meth:`connect` will use the
    same options, unless new ones are provided.
    """

    def __init__(
        self,
        hostname: Optional[str] = "localhost",
        port: Optional[int] = None,
        source_address: Optional[str] = None,
        timeout: Optional[float] = DEFAULT_TIMEOUT,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        use_tls: bool = False,
        start_tls: bool = False,
        validate_certs: bool = True,
        client_cert: Optional[str] = None,
        client_key: Optional[str] = None,
        tls_context: Optional[ssl.SSLContext] = None,
        cert_bundle: Optional[str] = None,
    ) -> None:
        """
        :keyword hostname:  Server name (or IP) to connect to. Defaults to "localhost".
        :keyword port: Server port. Defaults ``465`` if ``use_tls`` is ``True``,
            ``587`` if ``start_tls`` is ``True``, or ``25`` otherwise.
        :keyword source_address: The hostname of the client. Defaults to the
            result of :func:`socket.getfqdn`. Note that this call blocks.
        :keyword timeout: Default timeout value for the connection, in seconds.
            Defaults to 60.
        :keyword loop: event loop  to run on. If not set, uses
            :py:func:`asyncio.get_event_loop`.
        :keyword use_tls: If True, make the _initial_ connection to the server
            over TLS/SSL. Note that if the server supports STARTTLS only, this
            should be False.
        :keyword start_tls: If True, make the initial connection to the server
            over plaintext, and then upgrade the connection to TLS/SSL. Not
            compatible with use_tls.
        :keyword validate_certs: Determines if server certificates are
            validated. Defaults to True.
        :keyword client_cert: Path to client side certificate, for TLS
            verification.
        :keyword client_key: Path to client side key, for TLS verification.
        :keyword tls_context: An existing :py:class:`ssl.SSLContext`, for TLS
            verification. Mutually exclusive with ``client_cert``/
            ``client_key``.
        :keyword cert_bundle: Path to certificate bundle, for TLS verification.

        :raises ValueError: mutually exclusive options provided
        """
        self.protocol = None  # type: Optional[SMTPProtocol]
        self.transport = None  # type: Optional[asyncio.BaseTransport]

        # Kwarg defaults are provided here, and saved for connect.
        self.hostname = hostname
        self.port = port
        self.timeout = timeout
        self.use_tls = use_tls
        self._start_tls_on_connect = start_tls
        self._source_address = source_address
        self.validate_certs = validate_certs
        self.client_cert = client_cert
        self.client_key = client_key
        self.tls_context = tls_context
        self.cert_bundle = cert_bundle

        self.loop = loop or asyncio.get_event_loop()
        self._connect_lock = asyncio.Lock(loop=self.loop)

        self._validate_config()

    async def __aenter__(self) -> "SMTPConnection":
        if not self.is_connected:
            await self.connect()

        return self

    async def __aexit__(
        self, exc_type: Type[Exception], exc: Exception, traceback: Any
    ) -> None:
        if isinstance(exc, (ConnectionError, TimeoutError)):
            self.close()
            return

        try:
            await self.quit()
        except (SMTPServerDisconnected, SMTPResponseException, SMTPTimeoutError):
            pass

    @property
    def is_connected(self) -> bool:
        """
        Check if our transport is still connected.
        """
        return bool(self.protocol is not None and self.protocol.is_connected)

    @property
    def source_address(self) -> str:
        """
        Get the system hostname to be sent to the SMTP server.
        Simply caches the result of :func:`socket.getfqdn`.
        """
        if self._source_address is None:
            self._source_address = socket.getfqdn()

        return self._source_address

    def _update_settings_from_kwargs(
        self,
        hostname: Optional[str] = None,
        port: Optional[int] = None,
        source_address: Union[str, Default] = _default,
        timeout: Optional[Union[float, Default]] = _default,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        use_tls: Optional[bool] = None,
        start_tls: Optional[bool] = None,
        validate_certs: Optional[bool] = None,
        client_cert: Optional[Union[str, Default]] = _default,
        client_key: Optional[Union[str, Default]] = _default,
        tls_context: Optional[Union[ssl.SSLContext, Default]] = _default,
        cert_bundle: Optional[Union[str, Default]] = _default,
    ) -> None:
        """Update our configuration from the kwargs provided.

        This method can be called multiple times.
        """
        if hostname is not None:
            self.hostname = hostname
        if loop is not None:
            self.loop = loop
        if use_tls is not None:
            self.use_tls = use_tls
        if start_tls is not None:
            self._start_tls_on_connect = start_tls
        if validate_certs is not None:
            self.validate_certs = validate_certs
        if port is not None:
            self.port = port

        if timeout is not _default:
            self.timeout = cast(Optional[float], timeout)
        if source_address is not _default:
            self._source_address = cast(str, source_address)
        if client_cert is not _default:
            self.client_cert = cast(str, client_cert)
        if client_key is not _default:
            self.client_key = cast(str, client_key)
        if tls_context is not _default:
            self.tls_context = cast(ssl.SSLContext, tls_context)
        if cert_bundle is not _default:
            self.cert_bundle = cast(str, cert_bundle)

    def _validate_config(self) -> None:
        if self._start_tls_on_connect and self.use_tls:
            raise ValueError("The start_tls and use_tls options are not compatible.")

        if self.tls_context is not None and self.client_cert is not None:
            raise ValueError(
                "Either a TLS context or a certificate/key must be provided"
            )

    async def connect(self, **kwargs) -> SMTPResponse:
        """
        Initialize a connection to the server. Options provided to
        :meth:`.connect` take precedence over those used to initialize the
        class.

        :keyword hostname:  Server name (or IP) to connect to. Defaults to "localhost".
        :keyword port: Server port. Defaults ``465`` if ``use_tls`` is ``True``,
            ``587`` if ``start_tls`` is ``True``, or ``25`` otherwise.
        :keyword source_address: The hostname of the client. Defaults to the
            result of :func:`socket.getfqdn`. Note that this call blocks.
        :keyword timeout: Default timeout value for the connection, in seconds.
            Defaults to 60.
        :keyword loop: event loop to run on. If not set, uses
            :py:func:`asyncio.get_event_loop`.
        :keyword use_tls: If True, make the initial connection to the server
            over TLS/SSL. Note that if the server supports STARTTLS only, this
            should be False.
        :keyword start_tls: If True, make the initial connection to the server
            over plaintext, and then upgrade the connection to TLS/SSL. Not
            compatible with use_tls.
        :keyword validate_certs: Determines if server certificates are
            validated. Defaults to True.
        :keyword client_cert: Path to client side certificate, for TLS.
        :keyword client_key: Path to client side key, for TLS.
        :keyword tls_context: An existing :py:class:`ssl.SSLContext`, for TLS.
            Mutually exclusive with ``client_cert``/``client_key``.
        :keyword cert_bundle: Path to certificate bundle, for TLS verification.

        :raises ValueError: mutually exclusive options provided
        """
        await self._connect_lock.acquire()

        self._update_settings_from_kwargs(**kwargs)
        self._validate_config()

        # Set default port last in case use_tls or start_tls is provided
        if self.port is None:
            if self.use_tls:
                self.port = SMTP_TLS_PORT
            elif self._start_tls_on_connect:
                self.port = SMTP_STARTTLS_PORT
            else:
                self.port = SMTP_PORT

        try:
            response = await self._create_connection()
        except Exception as exc:
            self.close()  # Reset our state to disconnected
            raise exc

        return response

    async def _create_connection(self) -> SMTPResponse:
        protocol = SMTPProtocol(
            loop=self.loop, connection_lost_callback=self._connection_lost
        )

        tls_context = None  # type: Optional[ssl.SSLContext]
        if self.use_tls:
            tls_context = self._get_tls_context()

        connect_coro = self.loop.create_connection(  # type: ignore
            lambda: protocol, host=self.hostname, port=self.port, ssl=tls_context
        )
        try:
            transport, _ = await asyncio.wait_for(connect_coro, timeout=self.timeout)
        except (ConnectionRefusedError, OSError) as exc:
            raise SMTPConnectError(
                "Error connecting to {host} on port {port}: {err}".format(
                    host=self.hostname, port=self.port, err=exc
                )
            ) from exc
        except asyncio.TimeoutError as exc:
            raise SMTPConnectTimeoutError(
                "Timed out connecting to {host} on port {port}".format(
                    host=self.hostname, port=self.port
                )
            ) from exc

        self.protocol = protocol
        self.transport = transport

        try:
            response = await protocol.read_response(timeout=self.timeout)
        except SMTPTimeoutError as exc:
            raise SMTPConnectTimeoutError(
                "Timed out waiting for server ready message"
            ) from exc

        if response.code != SMTPStatus.ready:
            raise SMTPConnectError(str(response))

        if self._start_tls_on_connect:
            await self.starttls()

        return response

    def _connection_lost(self, waiter: asyncio.Future) -> None:
        if waiter.cancelled() or waiter.exception() is not None:
            self.close()

    async def execute_command(
        self, *args: bytes, timeout: Optional[Union[float, Default]] = _default
    ) -> SMTPResponse:
        """
        Check that we're connected, if we got a timeout value, and then
        pass the command to the protocol.

        :raises SMTPServerDisconnected: connection lost
        """
        if self.protocol is None:
            raise SMTPServerDisconnected("Not connected")

        if timeout is _default:
            timeout = self.timeout
        timeout = cast(Optional[float], timeout)

        response = await self.protocol.execute_command(*args, timeout=timeout)

        # If the server is unavailable, be nice and close the connection
        if response.code == SMTPStatus.domain_unavailable:
            self.close()

        return response

    async def quit(
        self, timeout: Optional[Union[float, Default]] = _default
    ) -> SMTPResponse:
        raise NotImplementedError

    async def starttls(
        self,
        server_hostname: Optional[str] = None,
        validate_certs: Optional[bool] = None,
        client_cert: Optional[Union[str, Default]] = _default,
        client_key: Optional[Union[str, Default]] = _default,
        cert_bundle: Optional[Union[str, Default]] = _default,
        tls_context: Optional[Union[ssl.SSLContext, Default]] = _default,
        timeout: Optional[Union[float, Default]] = _default,
    ) -> SMTPResponse:
        raise NotImplementedError

    def _get_tls_context(self) -> ssl.SSLContext:
        """
        Build an SSLContext object from the options we've been given.
        """
        if self.tls_context is not None:
            context = self.tls_context
        else:
            # SERVER_AUTH is what we want for a client side socket
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.check_hostname = bool(self.validate_certs)
            if self.validate_certs:
                context.verify_mode = ssl.CERT_REQUIRED
            else:
                context.verify_mode = ssl.CERT_NONE

            if self.cert_bundle is not None:
                context.load_verify_locations(cafile=self.cert_bundle)

            if self.client_cert is not None:
                context.load_cert_chain(self.client_cert, keyfile=self.client_key)

        return context

    def close(self) -> None:
        """
        Closes the connection.
        """
        if self.transport is not None and not self.transport.is_closing():
            self.transport.close()

        if self._connect_lock.locked():
            self._connect_lock.release()

        self.protocol = None
        self.transport = None

    def get_transport_info(self, key: str) -> Any:
        """
        Get extra info from the transport.
        Supported keys:

            - ``peername``
            - ``socket``
            - ``sockname``
            - ``compression``
            - ``cipher``
            - ``peercert``
            - ``sslcontext``
            - ``sslobject``

        :raises SMTPServerDisconnected: connection lost
        """
        if self.transport is None:
            raise SMTPServerDisconnected("Disconnected from SMTP server")

        return self.transport.get_extra_info(key)
