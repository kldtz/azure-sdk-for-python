# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------
import platform
import socket
from typing import Dict, Any
import subprocess
import webbrowser
from urllib.parse import urlparse
import msal

from azure.core.exceptions import ClientAuthenticationError

from .. import CredentialUnavailableError
from .._constants import DEVELOPER_SIGN_ON_CLIENT_ID
from .._internal import AuthCodeRedirectServer, InteractiveCredential, wrap_exceptions, within_dac


class InteractiveBrowserCredential(InteractiveCredential):
    """Opens a browser to interactively authenticate a user.

    :func:`~get_token` opens a browser to a login URL provided by Azure Active Directory and authenticates a user
    there with the authorization code flow, using PKCE (Proof Key for Code Exchange) internally to protect the code.

    :keyword str authority: Authority of an Azure Active Directory endpoint, for example "login.microsoftonline.com",
        the authority for Azure Public Cloud (which is the default). :class:`~azure.identity.AzureAuthorityHosts`
        defines authorities for other clouds.
    :keyword str tenant_id: an Azure Active Directory tenant ID. Defaults to the "organizations" tenant, which can
        authenticate work or school accounts.
    :keyword str client_id: Client ID of the Azure Active Directory application users will sign in to. If
        unspecified, users will authenticate to an Azure development application.
    :keyword str login_hint: a username suggestion to pre-fill the login page's username/email address field. A user
        may still log in with a different username.
    :keyword str redirect_uri: a redirect URI for the application identified by `client_id` as configured in Azure
        Active Directory, for example "http://localhost:8400". This is only required when passing a value for
        **client_id**, and must match a redirect URI in the application's registration. The credential must be able to
        bind a socket to this URI.
    :keyword AuthenticationRecord authentication_record: :class:`AuthenticationRecord` returned by :func:`authenticate`
    :keyword bool disable_automatic_authentication: if True, :func:`get_token` will raise
        :class:`AuthenticationRequiredError` when user interaction is required to acquire a token. Defaults to False.
    :keyword cache_persistence_options: configuration for persistent token caching. If unspecified, the credential
        will cache tokens in memory.
    :paramtype cache_persistence_options: ~azure.identity.TokenCachePersistenceOptions
    :keyword int timeout: seconds to wait for the user to complete authentication. Defaults to 300 (5 minutes).
    :keyword bool disable_instance_discovery: Determines whether or not instance discovery is performed when attempting
        to authenticate. Setting this to true will completely disable both instance discovery and authority validation.
        This functionality is intended for use in scenarios where the metadata endpoint cannot be reached, such as in
        private clouds or Azure Stack. The process of instance discovery entails retrieving authority metadata from
        https://login.microsoft.com/ to validate the authority. By setting this to **True**, the validation of the
        authority is disabled. As a result, it is crucial to ensure that the configured authority host is valid and
        trustworthy.
    :raises ValueError: invalid **redirect_uri**

    .. admonition:: Example:

        .. literalinclude:: ../samples/credential_creation_code_snippets.py
            :start-after: [START create_interactive_browser_credential]
            :end-before: [END create_interactive_browser_credential]
            :language: python
            :dedent: 4
            :caption: Create an InteractiveBrowserCredential.
    """

    def __init__(self, **kwargs: Any) -> None:
        redirect_uri = kwargs.pop("redirect_uri", None)
        if redirect_uri:
            self._parsed_url = urlparse(redirect_uri)
            if not (self._parsed_url.hostname and self._parsed_url.port):
                raise ValueError('"redirect_uri" must be a URL with port number, for example "http://localhost:8400"')
        else:
            self._parsed_url = None

        self._login_hint = kwargs.pop("login_hint", None)
        self._timeout = kwargs.pop("timeout", 300)
        self._server_class = kwargs.pop("_server_class", AuthCodeRedirectServer)
        client_id = kwargs.pop("client_id", DEVELOPER_SIGN_ON_CLIENT_ID)
        super(InteractiveBrowserCredential, self).__init__(client_id=client_id, **kwargs)

    @wrap_exceptions
    def _request_token(self, *scopes: str, **kwargs: Any) -> Dict:
        scopes = list(scopes)  # type: ignore
        claims = kwargs.get("claims")
        app = self._get_app(**kwargs)
        if isinstance(app, msal.ConfidentialClientApplication):
            server = None
            if self._parsed_url:
                redirect_uri = "http://{}:{}".format(self._parsed_url.hostname, self._parsed_url.port)
                try:
                    server = self._server_class(self._parsed_url.hostname, self._parsed_url.port, timeout=self._timeout)
                except socket.error as ex:
                    raise CredentialUnavailableError(message="Couldn't start an HTTP server on " + redirect_uri) from ex
            else:
                for port in range(8400, 9000):
                    try:
                        server = self._server_class("localhost", port, timeout=self._timeout)
                        redirect_uri = "http://localhost:{}".format(port)
                        break
                    except socket.error:
                        continue  # keep looking for an open port

            if not server:
                raise CredentialUnavailableError(message="Couldn't start an HTTP server on localhost")

            flow = app.initiate_auth_code_flow(
                scopes,
                redirect_uri=redirect_uri,
                prompt="select_account",
                claims_challenge=claims,
                login_hint=self._login_hint,
            )
            if "auth_uri" not in flow:
                raise CredentialUnavailableError("Failed to begin authentication flow")

            if not _open_browser(flow["auth_uri"]):
                raise CredentialUnavailableError(message="Failed to open a browser")

            # block until the server times out or receives the post-authentication redirect
            response = server.wait_for_redirect()
            if not response:
                raise ClientAuthenticationError(
                    message="Timed out after waiting {} seconds for the user to authenticate".format(self._timeout)
                )

            # redeem the authorization code for a token
            return app.acquire_token_by_auth_code_flow(flow, response, scopes=scopes, claims_challenge=claims)

        port = self._parsed_url.port if self._parsed_url else None

        try:
            result = app.acquire_token_interactive(
                scopes=scopes,
                login_hint=self._login_hint,
                claims_challenge=claims,
                timeout=self._timeout,
                prompt="select_account",
                port=port,
                parent_window_handle=self._parent_window_handle,
                enable_msa_passthrough=self._enable_msa_passthrough,
            )
        except socket.error as ex:
            raise CredentialUnavailableError(message="Couldn't start an HTTP server.") from ex
        if "access_token" not in result and "error_description" in result:
            if within_dac.get():
                raise CredentialUnavailableError(message=result["error_description"])
            raise ClientAuthenticationError(message=result.get("error_description"))
        if "access_token" not in result:
            if within_dac.get():
                raise CredentialUnavailableError(message="Failed to authenticate user")
            raise ClientAuthenticationError(message="Failed to authenticate user")

        # base class will raise for other errors
        return result


def _open_browser(url):
    opened = webbrowser.open(url)
    if not opened:
        uname = platform.uname()
        system = uname[0].lower()
        release = uname[2].lower()
        if "microsoft" in release and system == "linux":
            kwargs = {"timeout": 5}

            try:
                exit_code = subprocess.call(
                    ["powershell.exe", "-NoProfile", "-Command", 'Start-Process "{}"'.format(url)], **kwargs
                )
                opened = exit_code == 0
            except Exception:  # pylint:disable=broad-except
                # powershell.exe isn't available, or the subprocess timed out
                pass
    return opened
