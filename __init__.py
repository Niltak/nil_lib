#! /user/bin/env python3 -i

# Kat Lib Commands v2
# Developed by Katlin Sampson

import os
import re
import yaml
import json
import logging
import base64
import netmiko
from datetime import date
from textfsm import TextFSM
from getpass import getpass
from platform import system
from subprocess import run, DEVNULL
from concurrent.futures import ThreadPoolExecutor


def verify_pwd(
    user, pwd=None, test_switch_ip='10.242.242.151') -> str:
    '''
    Verifies username and password. Outputs password.
    '''
    if not pwd:
        pwd = getpass()

    target_test_switch = {
        'device_type': 'cisco_ios',
        'host': test_switch_ip,
        'username': user,
        'password': pwd}

    try:
        with netmiko.ConnectHandler(**target_test_switch):
            pass
    except netmiko.NetMikoAuthenticationException:
        logging.error('Failed Password!')
        exit()
    except netmiko.NetMikoTimeoutException:
        logging.critical('Could Not Connect to Test Switch!')
        exit()
    except Exception:
        logging.error('Something went wrong with the test password!')
        exit()

    return pwd


def switch_connect(switch):
    '''
    Connects to a switch. Returns switch connection or error dict.
    '''
    error = {'name': False, 'output': switch['host']}

    if switch['device_type'] == 'autodetect':
        try:
            device_type = netmiko.SSHDetect(**switch)
        # TODO: add more logging
        except Exception:
            del switch['password']
            return error

        switch['device_type'] = device_type.autodetect()
        if switch['device_type'] is None:
            if 'Cisco Nexus Operating System' in device_type.initial_buffer:
                switch['device_type'] = 'cisco_nxos'
            else:
                switch['device_type'] = device_type.autodetect()
                if switch['device_type'] is None:
                    logging.warning(f"{switch['host']} had no auto-detected IOS")
                    switch['device_type'] = 'cisco_ios'

    try:
        switch_connection = netmiko.ConnectHandler(**switch)
    except netmiko.NetmikoAuthenticationException:
        logging.debug(f"Could not access {switch['host']}")
        return error
    except netmiko.NetmikoTimeoutException:
        logging.debug(f"Connection timed out on {switch['host']}")
        return error
    except EOFError:
        logging.warning(f"Connection closed on {switch['host']}")
        return error

    return switch_connection


def switch_send_command(
    switch, command_list, fsm=False, fsm_template=None, read_timeout=20) -> dict:
    '''
    Uses switch connection object to send list of commands. Can use textFSM.
    '''
    if not isinstance(command_list, list):
        command_list = [command_list]
    try:
        with switch_connect(switch) as connection:
            switch_name = connection.find_prompt()[:-1]
            switch_output = []
            for command in command_list:
                switch_output.append(
                    connection.send_command(
                        command, use_textfsm=fsm,
                        textfsm_template=fsm_template,
                        delay_factor=5, read_timeout=read_timeout))
    except AttributeError:
        logging.warning(f"Could not connect to {switch['host']}")
        return {'name': False, 'output': switch['host']}

    if fsm and isinstance(switch_output, list):
        if len(switch_output) == 1:
            switch_output = switch_output[0]

    return {
        'name': switch_name,
        'host': switch['host'],
        'output': switch_output,
        'device_type': switch['device_type']}


def switch_list_send_command(
    switch_list, command_list, fsm=False, fsm_template=None, read_timeout=20) -> list:
    '''
    Send a list of commands to a list of switches. Can use textFSM.
    '''
    if not isinstance(switch_list, list):
        switch_list = [switch_list]
    if fsm_template:
        if not fsm_template.endswith('.fsm'):
            fsm_template += '.fsm'

    with ThreadPoolExecutor(max_workers=24) as pool:
        repeat = len(switch_list)
        switch_list_output = pool.map(
            switch_send_command,
            switch_list,
            [command_list] * repeat,
            [fsm] * repeat,
            [fsm_template] * repeat,
            [read_timeout] * repeat)

    return list(switch_list_output)


def switch_send_reload(
    switch,
    delay=None,
    cancel=False) -> dict:
    '''
    '''
    if not delay:
        command = 'reload'
    else:
        command = f'reload in {delay}'
    try:
        with switch_connect(switch) as connection:
            switch_name = connection.find_prompt()[:-1]
            switch_output = []
            if not cancel:
                switch_output.append(
                    connection.send_command(
                        command,
                        expect_string="Proceed with reload",
                        delay_factor=5,
                        read_timeout=20))
                switch_output.append(
                    connection.send_command(
                        '\n',
                        delay_factor=5,
                        read_timeout=20))
            if cancel:
                switch_output.append(
                    connection.send_command(
                        'reload cancel',
                        delay_factor=5,
                        read_timeout=20))
    except AttributeError:
        logging.warning(f"Could not connect to {switch['host']}")
        return {'name': False, 'output': switch['host']}
    except netmiko.exceptions.ReadTimeout:
        logging.warning(f"Host failed {switch['host']}")
        return {'name': False, 'output': switch['host']}

    return {
        'name': switch_name,
        'host': switch['host'],
        'output': switch_output,
        'device_type': switch['device_type']
    }


def switch_list_send_reload(
    switch_list,
    delay=None,
    cancel=False) -> list:
    '''
    '''
    if not isinstance(switch_list, list):
        switch_list = [switch_list]

    with ThreadPoolExecutor(max_workers=24) as pool:
        switch_list_output = pool.map(
            switch_send_reload,
            switch_list,
            [delay] * len(switch_list),
            [cancel] * len(switch_list))

    return list(switch_list_output)


def switch_config_file(switch, config_file) -> dict:
    '''
    Uses switch connection to send a configuration file.
    Returns the switch output.
    '''
    try:
        with switch_connect(switch) as connection:
            switch_output = connection.send_config_from_file(config_file)
            switch_output_diff = f'{connection.find_prompt()}\n'
            if switch['device_type'] == 'cisco_nxos':
                sh_diff = 'sh run diff'
            else:
                sh_diff = 'sh archive config differences'
            switch_output_diff += f'{connection.send_command(sh_diff)}'
            switch_output += f'{connection.save_config()}\n\n'
    except AttributeError:
        return {'name': False, 'output': switch['host']}
    except FileNotFoundError:
        logging.warning('Failed to find command file!')
        exit()
    except OSError:
        logging.warning(f"Something is wrong with {switch['host']}")
        return {'name': False, 'output': switch['host']}
    except netmiko.NetmikoTimeoutException:
        logging.warning(f"Connection timed out on {switch['host']}")
        return {'name': False, 'output': switch['host']}
    except Exception:
        logging.warning(f'catch all was triggered for switch_config_file {Exception}')
        return {'name': False, 'output': switch['host']}

    return {
        'name': switch['host'],
        'output': switch_output,
        'diff': switch_output_diff,
        'device_type': switch['device_type']}


def switch_list_config_file(
    switch_list, config_file, log_file_name) -> None:
    '''
    Send configuration file to a list of switches.
    Creates log files for the command outputs and configuration differences.
    '''
    if not isinstance(switch_list, list):
        switch_list = [switch_list]

    with ThreadPoolExecutor(max_workers=24) as pool:
        switch_list_output = pool.map(
            switch_config_file, switch_list,
            [config_file] * len(switch_list))

    switch_list_log, switch_list_diff, switch_errored = [], [], []
    for switch_output in switch_list_output:
        if not switch_output['name']:
            switch_errored.append(switch_output['output'])
            continue
        switch_list_log.append(switch_output['output'])
        switch_list_diff.append(switch_output['diff'])

    if switch_errored:
        error_entry = 'The following switches could not be connected to:\n'
        for switch in switch_errored:
            error_entry += f'{switch}\n'
        error_entry += '\n\n'
        switch_list_log.insert(0, error_entry)

    # TODO:Refactor this regex
    new_cert_regex = 'crypto pki.*\n.*-certificate[\w\d\s\n-]*quit\n'
    old_cert_regex = 'crypto pki.*\n.*certificate.*\n'
    for index, diff in enumerate(switch_list_diff):
        trim_diff = re.sub(new_cert_regex, '', diff)
        trim_diff = re.sub(old_cert_regex, '', trim_diff)
        switch_list_diff[index] = '\n' + trim_diff

    log_file_name = f"{date.today().strftime('%m-%d-%Y')}--{log_file_name}"

    file_create(log_file_name, 'logs/network/', switch_list_log)
    file_create(f'{log_file_name} (diff)', 'logs/network/', switch_list_diff)


def format_switch_list(
    switch_list, user, pwd=None, device_type='autodetect') -> list:
    '''
    Formats a list of switches based on IPs or a dict of host and device type.
    Returns a list of switches ready for connection functions.
    '''
    if not pwd:
        pwd = verify_pwd(user)
    if isinstance(pwd, bytes):
        pwd = base64.b85decode(pwd).decode('utf-8')
    if not isinstance(switch_list, list):
        switch_list = [switch_list]

    switch_template = {
        'username': user,
        'password': pwd,
        'fast_cli': False}

    for index, switch in enumerate(switch_list):
        switch_format = switch_template.copy()
        if isinstance(switch, dict):
            switch_format.update(switch)
            if 'device_type' not in switch_format.keys():
                switch_format['device_type'] = device_type
        else:
            switch_format['device_type'] = device_type
            switch_format['host'] = switch

        switch_list[index] = switch_format

    return switch_list


def format_site_yaml(
    site_yaml, user, pwd=None,
    switch_group=None, switch_location=None,
    switch_role=None, switch_names=None) -> list:
    '''
    Formats site yaml file into list of switches ready for connection functions.
    Can search site yaml for certain keys. (Groups, Location, Roles, and Hostnames)
    '''
    # TODO: Need to refactor
    if not pwd:
        pwd = verify_pwd(user)
    if switch_names:
        if not isinstance(switch_names, list):
            switch_names = [switch_names]

    if not site_yaml.endswith('.yml'):
        site_yaml = f'site_info/{site_yaml}/{site_yaml}.yml'

    switch_list = file_loader(site_yaml)['Switchlist']

    switch_list_results = []
    for switch in switch_list:
        searched_group = True if not switch_group else switch_group in switch['groups']
        searched_location = True if not switch_location else switch_location == switch['data']['location']
        searched_role = True if not switch_role else switch_role == switch['data']['role']
        searched_name = True if not switch_names else switch['hostname'] in switch_names

        if searched_group and searched_location and searched_role and searched_name:
            switch_format = {
                'host': switch['host'],
                'device_type': switch['data']['device_type']
            }
            switch_list_results.append(switch_format)

    return format_switch_list(switch_list_results, user, pwd=pwd)


def search_within_list(
    search_value, search_list, search_key):
    '''
    Search list of dictionaries for a value within a certain key.
    '''
    for search_list_item in search_list:
        if search_list_item[search_key] == search_value:
            return search_list_item
    return False


def prompt_yes_no(prompt_text) -> bool:
    '''
    Prompt for confirmation.
    '''
    yes_no = input(f'{prompt_text} -> ').lower()[:1]

    return True if yes_no == 'y' else False


def file_loader(file_load, file_lines=None) -> list:
    '''
    Loads file into a list.
    Can load yaml, json, textFSM, or txt~ files.
    '''
    with open(file_load, 'r') as file_info:
        debug_info = os.getcwd()
        if file_load.endswith('yaml') or file_load.endswith('yml'):
            return yaml.load(file_info, Loader=yaml.CBaseLoader)
        elif file_load.endswith('json'):
            return json.load(file_info)
        elif file_load.endswith('fsm'):
            return TextFSM(file_info)
        else:
            if file_lines:
                data = file_info.readlines()
                for line in data[:]:
                    if line.endswith('\n'):
                        data.remove(line)
                        data.append(line[:-1])
                return data
            return [file_info.read()]


def file_create(
    file_name, file_dir, data,
    file_extension='txt', override=False) -> None:
    '''
    Creates file. Will create folder path as needed.
    Can create yaml, json, or txt~ files.
    '''
    # TODO: Refactor
    if file_dir:
        if file_dir[-1:] != '/':
            file_dir += '/'
        if not os.path.isdir(file_dir) and file_dir:
            os.makedirs(file_dir)

    file_url = f'{file_dir}{file_name}.{file_extension}'

    if not override and os.path.isfile(file_url):
        file_url = f'{file_dir}{file_name}_new.{file_extension}'

    with open(file_url, 'w') as data_file:
        if file_extension == 'yaml' or file_extension == 'yml':
            yaml.Dumper.ignore_aliases = lambda *args: True
            data_file.writelines(yaml.dump(data, sort_keys=False, Dumper=IndentDumper))
        elif file_extension == 'json':
            json.dump(data, data_file, sort_keys=False, indent=1)
        elif file_extension == 'txt' or 'ini':
            data_file.writelines(data)


def ping(host, attempts='3'):
    '''
    '''
    suffix = '-c'
    if system().lower() == 'windows':
        suffix = '-n'

    results = run(
        f'ping {host} {suffix} {attempts}',
        stdout=DEVNULL)

    if results.returncode != 0:
        return host


def ping_list(host_list, attempts='3') -> list:
    '''
    '''
    if not isinstance(host_list, list):
        host_list = [host_list]

    with ThreadPoolExecutor(max_workers=30) as pool:
        ping_output = pool.map(
            ping,
            host_list,
            attempts * len(host_list))

    ping_output_list = list(ping_output)

    for output in ping_output_list[:]:
        if not output:
            ping_output_list.remove(output)

    return ping_output_list


# yaml offical fix
class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(IndentDumper, self).increase_indent(flow, False)


if __name__ == "__main__":
    pass
