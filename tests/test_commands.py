"""
Lower level SMTP command tests.
"""
import asyncio

import pytest

from aiosmtplib import (
    SMTPDataError,
    SMTPHeloError,
    SMTPResponseException,
    SMTPStatus,
    SMTPTimeoutError,
)


pytestmark = pytest.mark.asyncio(forbid_global_loop=True)


async def test_helo_ok(smtp_client, smtpd_server):
    async with smtp_client:
        response = await smtp_client.helo()

        assert response.code == SMTPStatus.completed


async def test_helo_with_hostname(smtp_client, smtpd_server):
    async with smtp_client:
        response = await smtp_client.helo(hostname="example.com")

        assert response.code == SMTPStatus.completed


async def test_helo_error(smtp_client, smtpd_server, smtpd_handler, monkeypatch):
    async def helo_response(self, session, envelope, hostname):
        return "501 oh noes"

    monkeypatch.setattr(smtpd_handler, "handle_HELO", helo_response, raising=False)

    async with smtp_client:
        with pytest.raises(SMTPHeloError):
            await smtp_client.helo()


async def test_ehlo_ok(smtp_client, smtpd_server):
    async with smtp_client:
        response = await smtp_client.ehlo()

        assert response.code == SMTPStatus.completed


async def test_ehlo_with_hostname(smtp_client, smtpd_server):
    async with smtp_client:
        response = await smtp_client.ehlo(hostname="example.com")

        assert response.code == SMTPStatus.completed


async def test_ehlo_error(smtp_client, smtpd_server, smtpd_handler, monkeypatch):
    async def ehlo_response(self, session, envelope, hostname):
        return "501 oh noes"

    monkeypatch.setattr(smtpd_handler, "handle_EHLO", ehlo_response, raising=False)

    async with smtp_client:
        with pytest.raises(SMTPHeloError):
            await smtp_client.ehlo()


async def test_ehlo_parses_esmtp_extensions(
    smtp_client, smtpd_server, smtpd_handler, monkeypatch
):
    async def ehlo_response(self, session, envelope, hostname):
        return """250-PIPELINING
250-DSN
250-ENHANCEDSTATUSCODES
250-EXPN
250-HELP
250-SAML
250-SEND
250-SOML
250-TURN
250-XADR
250-XSTA
250-ETRN
250 XGEN"""

    monkeypatch.setattr(smtpd_handler, "handle_EHLO", ehlo_response, raising=False)

    async with smtp_client:
        await smtp_client.ehlo()

        # 8BITMIME and SIZE are supported by default in aiosmtpd.
        assert smtp_client.supports_extension("8bitmime")
        assert smtp_client.supports_extension("size")

        assert smtp_client.supports_extension("pipelining")
        assert smtp_client.supports_extension("ENHANCEDSTATUSCODES")
        assert not smtp_client.supports_extension("notreal")


async def test_ehlo_with_no_extensions(
    smtp_client, smtpd_server, aiosmtpd_class, monkeypatch
):
    async def ehlo_response(self, hostname):
        await self.push("250 all good")

    monkeypatch.setattr(aiosmtpd_class, "smtp_EHLO", ehlo_response)

    async with smtp_client:
        await smtp_client.ehlo()

        assert not smtp_client.supports_extension("size")


async def test_ehlo_or_helo_if_needed_ehlo_success(smtp_client, smtpd_server):
    async with smtp_client:
        assert smtp_client.is_ehlo_or_helo_needed is True

        await smtp_client._ehlo_or_helo_if_needed()

        assert smtp_client.is_ehlo_or_helo_needed is False


async def test_ehlo_or_helo_if_needed_helo_success(
    smtp_client, smtpd_server, smtpd_handler, monkeypatch
):
    async def ehlo_response(self, session, envelope, hostname):
        return "500 no bueno"

    monkeypatch.setattr(smtpd_handler, "handle_EHLO", ehlo_response, raising=False)

    async with smtp_client:
        assert smtp_client.is_ehlo_or_helo_needed is True

        await smtp_client._ehlo_or_helo_if_needed()

        assert smtp_client.is_ehlo_or_helo_needed is False


async def test_ehlo_or_helo_if_needed_neither_succeeds(
    smtp_client, smtpd_server, smtpd_handler, monkeypatch
):
    async def ehlo_or_helo_response(self, session, envelope, hostname):
        return "500 no bueno"

    monkeypatch.setattr(
        smtpd_handler, "handle_EHLO", ehlo_or_helo_response, raising=False
    )
    monkeypatch.setattr(
        smtpd_handler, "handle_HELO", ehlo_or_helo_response, raising=False
    )

    async with smtp_client:
        assert smtp_client.is_ehlo_or_helo_needed is True

        with pytest.raises(SMTPHeloError):
            await smtp_client._ehlo_or_helo_if_needed()


async def test_ehlo_or_helo_if_needed_disconnect_on_ehlo(
    smtp_client,
    smtpd_server,
    smtpd_handler,
    monkeypatch,
    smtpd_commands,
    smtpd_responses,
):
    async def ehlo_or_helo_response(*args):
        smtpd_server.close()
        await smtpd_server.wait_closed()

        return "501 oh noes"

    monkeypatch.setattr(
        smtpd_handler, "handle_EHLO", ehlo_or_helo_response, raising=False
    )
    monkeypatch.setattr(
        smtpd_handler, "handle_HELO", ehlo_or_helo_response, raising=False
    )

    async with smtp_client:
        with pytest.raises(SMTPHeloError):
            await smtp_client._ehlo_or_helo_if_needed()


async def test_rset_ok(smtp_client, smtpd_server):
    async with smtp_client:
        response = await smtp_client.rset()

        assert response.code == SMTPStatus.completed
        assert response.message == "OK"


async def test_rset_error(smtp_client, smtpd_server, smtpd_handler, monkeypatch):
    async def rset_response(self, session, envelope):
        return "501 oh noes"

    monkeypatch.setattr(smtpd_handler, "handle_RSET", rset_response, raising=False)

    async with smtp_client:
        with pytest.raises(SMTPResponseException):
            await smtp_client.rset()


async def test_noop_ok(smtp_client, smtpd_server):
    async with smtp_client:
        response = await smtp_client.noop()

        assert response.code == SMTPStatus.completed
        assert response.message == "OK"


async def test_noop_error(smtp_client, smtpd_server, smtpd_handler, monkeypatch):
    async def noop_response(self, session, envelope, arg):
        return "501 oh noes"

    monkeypatch.setattr(smtpd_handler, "handle_NOOP", noop_response, raising=False)

    async with smtp_client:
        with pytest.raises(SMTPResponseException):
            await smtp_client.noop()


async def test_vrfy_ok(smtp_client, smtpd_server):
    nice_address = "test@example.com"
    async with smtp_client:
        response = await smtp_client.vrfy(nice_address)

        assert response.code == SMTPStatus.cannot_vrfy


async def test_vrfy_with_blank_address(smtp_client, smtpd_server):
    bad_address = ""
    async with smtp_client:
        with pytest.raises(SMTPResponseException):
            await smtp_client.vrfy(bad_address)


async def test_expn_ok(smtp_client, smtpd_server, aiosmtpd_class, monkeypatch):
    async def expn_response(self, arg):
        await self.push(
            """250-Joseph Blow <jblow@example.com>
250 Alice Smith <asmith@example.com>"""
        )

    monkeypatch.setattr(aiosmtpd_class, "smtp_EXPN", expn_response)

    async with smtp_client:
        response = await smtp_client.expn("listserv-members")
        assert response.code == SMTPStatus.completed


async def test_expn_error(smtp_client, smtpd_server):
    """
    Since EXPN isn't implemented by aiosmtpd, it raises an exception by default.
    """
    async with smtp_client:
        with pytest.raises(SMTPResponseException):
            await smtp_client.expn("a-list")


async def test_help_ok(smtp_client, smtpd_server):
    async with smtp_client:
        help_message = await smtp_client.help()

        assert "Supported commands" in help_message


async def test_help_error(smtp_client, smtpd_server, aiosmtpd_class, monkeypatch):
    async def help_response(self, arg):
        await self.push("501 error")

    monkeypatch.setattr(aiosmtpd_class, "smtp_HELP", help_response)

    async with smtp_client:
        with pytest.raises(SMTPResponseException):
            await smtp_client.help()


async def test_quit_error(smtp_client, smtpd_server, smtpd_handler, monkeypatch):
    async def quit_response(self, arg):
        return "501 error"

    monkeypatch.setattr(smtpd_handler, "handle_QUIT", quit_response, raising=False)

    async with smtp_client:
        with pytest.raises(SMTPResponseException):
            await smtp_client.quit()


async def test_supported_methods(smtp_client, smtpd_server):
    async with smtp_client:
        response = await smtp_client.ehlo()

        assert response.code == SMTPStatus.completed
        assert smtp_client.supports_extension("size")
        assert smtp_client.supports_extension("help")
        assert not smtp_client.supports_extension("bogus")


async def test_mail_ok(smtp_client, smtpd_server):
    async with smtp_client:
        await smtp_client.ehlo()
        response = await smtp_client.mail("j@example.com")

        assert response.code == SMTPStatus.completed
        assert response.message == "OK"


async def test_mail_error(smtp_client, smtpd_server, smtpd_handler, monkeypatch):
    async def mail_response(self, arg):
        return "501 error"

    monkeypatch.setattr(smtpd_handler, "handle_MAIL", mail_response, raising=False)

    async with smtp_client:
        await smtp_client.ehlo()

        with pytest.raises(SMTPResponseException):
            await smtp_client.mail("test@example.com")


async def test_rcpt_ok(smtp_client, smtpd_server):
    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("j@example.com")

        response = await smtp_client.rcpt("test@example.com")

        assert response.code == SMTPStatus.completed
        assert response.message == "OK"


async def test_rcpt_options_ok(smtp_client, smtpd_server, aiosmtpd_class, monkeypatch):
    # RCPT options are not implemented in aiosmtpd, so force success response
    async def rcpt_response(self, arg):
        await self.push("250 rcpt ok")

    monkeypatch.setattr(aiosmtpd_class, "smtp_RCPT", rcpt_response)

    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("j@example.com")

        response = await smtp_client.rcpt(
            "test@example.com", options=["NOTIFY=FAILURE,DELAY"]
        )

        assert response.code == SMTPStatus.completed


async def test_rcpt_options_not_implemented(smtp_client, smtpd_server):
    # RCPT options are not implemented in aiosmtpd, so any option will return 555
    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("j@example.com")

        with pytest.raises(SMTPResponseException) as err:
            await smtp_client.rcpt("test@example.com", options=["OPT=1"])
            assert err.code == SMTPStatus.syntax_error


async def test_rcpt_error(smtp_client, smtpd_server, smtpd_handler, monkeypatch):
    async def rcpt_response(self, arg):
        return "501 error"

    monkeypatch.setattr(smtpd_handler, "handle_RCPT", rcpt_response, raising=False)

    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("j@example.com")

        with pytest.raises(SMTPResponseException):
            await smtp_client.rcpt("test@example.com")


async def test_data_ok(smtp_client, smtpd_server):
    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("j@example.com")
        await smtp_client.rcpt("test@example.com")
        response = await smtp_client.data("HELLO WORLD")

        assert response.code == SMTPStatus.completed
        assert response.message == "OK"


async def test_data_with_timeout_arg(smtp_client, smtpd_server):
    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("j@example.com")
        await smtp_client.rcpt("test@example.com")
        response = await smtp_client.data("HELLO WORLD", timeout=10)

        assert response.code == SMTPStatus.completed
        assert response.message == "OK"


async def test_data_error(smtp_client, smtpd_server, aiosmtpd_class, monkeypatch):
    async def data_response(self, arg):
        await self.push("501 error")

    monkeypatch.setattr(aiosmtpd_class, "smtp_DATA", data_response)

    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("admin@example.com")
        await smtp_client.rcpt("test@example.com")
        with pytest.raises(SMTPDataError):
            await smtp_client.data("TEST MESSAGE")


async def test_data_complete_error(
    smtp_client, smtpd_server, smtpd_handler, monkeypatch
):
    async def data_response(self, arg):
        return "501 error"

    monkeypatch.setattr(smtpd_handler, "handle_DATA", data_response, raising=False)

    async with smtp_client:
        await smtp_client.ehlo()
        await smtp_client.mail("admin@example.com")
        await smtp_client.rcpt("test@example.com")
        with pytest.raises(SMTPDataError):
            await smtp_client.data("TEST MESSAGE")


async def test_command_timeout_error(
    smtp_client, smtpd_server, smtpd_handler, monkeypatch, event_loop
):
    async def ehlo_response(self, session, envelope, hostname):
        await asyncio.sleep(0.01, loop=event_loop)
        return "250 OK :)"

    monkeypatch.setattr(smtpd_handler, "handle_EHLO", ehlo_response, raising=False)

    async with smtp_client:
        with pytest.raises(SMTPTimeoutError):
            await smtp_client.ehlo(timeout=0.001)


async def test_gibberish_raises_exception(
    smtp_client, smtpd_server, smtpd_handler, monkeypatch
):
    async def noop_response(self, session, envelope, arg):
        return "sdfjlfwqejflqw"

    monkeypatch.setattr(smtpd_handler, "handle_NOOP", noop_response, raising=False)

    async with smtp_client:
        with pytest.raises(SMTPResponseException):
            await smtp_client.noop()
