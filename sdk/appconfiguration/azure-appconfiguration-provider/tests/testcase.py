# coding: utf-8
# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------
from devtools_testutils import AzureRecordedTestCase
from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting, FeatureFlagConfigurationSetting
from azure.appconfiguration.provider import SettingSelector, load
import os


class AppConfigTestCase(AzureRecordedTestCase):
    def create_aad_client(
        self,
        appconfiguration_endpoint_string,
        trim_prefixes=[],
        selects={SettingSelector(key_filter="*", label_filter="\0")},
        keyvault_secret_url=None,
        refresh_on=None,
        refresh_interval=30,
    ):
        cred = self.get_credential(AzureAppConfigurationClient)

        client = AzureAppConfigurationClient(appconfiguration_endpoint_string, cred)
        setup_configs(client, keyvault_secret_url)
        return load(
            credential=cred,
            endpoint=appconfiguration_endpoint_string,
            trim_prefixes=trim_prefixes,
            selects=selects,
            refresh_on=refresh_on,
            refresh_interval=refresh_interval,
        )

    def create_client(
        self,
        appconfiguration_connection_string,
        trim_prefixes=[],
        selects={SettingSelector(key_filter="*", label_filter="\0")},
        keyvault_secret_url=None,
        refresh_on=None,
        refresh_interval=30,
    ):
        client = AzureAppConfigurationClient.from_connection_string(appconfiguration_connection_string)
        setup_configs(client, keyvault_secret_url)
        return load(
            connection_string=appconfiguration_connection_string,
            trim_prefixes=trim_prefixes,
            selects=selects,
            refresh_on=refresh_on,
            refresh_interval=refresh_interval,
        )


def setup_configs(client, keyvault_secret_url):
    for config in get_configs(keyvault_secret_url):
        client.set_configuration_setting(config)


def get_configs(keyvault_secret_url):
    configs = []
    configs.append(create_config_setting("message", "\0", "hi"))
    configs.append(create_config_setting("message", "dev", "test"))
    configs.append(create_config_setting("my_json", "\0", '{"key": "value"}', "application/json"))
    configs.append(create_config_setting("test.trimmed", "\0", "key"))
    configs.append(create_config_setting("refresh_message", "\0", "original value"))
    configs.append(create_config_setting("non_refreshed_message", "\0", "Static"))
    configs.append(
        create_config_setting(
            ".appconfig.featureflag/Alpha",
            "\0",
            '{	"id": "Alpha", "description": "", "enabled": false, "conditions": {	"client_filters": []	}}',
            "application/vnd.microsoft.appconfig.ff+json;charset=utf-8",
        )
    )
    configs.append(
        create_config_setting(
            "secret",
            "prod",
            '{"uri":"' + keyvault_secret_url + '"}',
            "application/vnd.microsoft.appconfig.keyvaultref+json;charset=utf-8",
        )
    )
    return configs


def create_config_setting(key, label, value, content_type="text/plain"):
    return ConfigurationSetting(
        key=key,
        label=label,
        value=value,
        content_type=content_type,
    )


def create_feature_flag_config_setting(key, label, enabled):
    return FeatureFlagConfigurationSetting(
        feature_id=key,
        label=label,
        enabled=enabled,
    )
