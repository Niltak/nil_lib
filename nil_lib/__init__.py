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
from subprocess import call, DEVNULL
from concurrent.futures import ThreadPoolExecutor


def verify_pwd(
    user, pwd=None, test_switch_ip='10.242.242.151') -> str:
    '''
    Verifies username and password against a test switch via SSH.

    Args:
        user (str): Username for authentication
        pwd (str, optional): Password. Prompts if not provided.
        test_switch_ip (str): IP of test switch for validation (default: 10.242.242.151)

    Returns:
        str: Valid password if authentication succeeds

    Raises:
        SystemExit: On authentication failure or connection issues
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
    Establishes SSH connection to a network device.

    Args:
        switch (dict): Device config with host, username, password, device_type

    Returns:
        Connection object on success, error dict on failure
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
    switch, command_list, fsm=False, fsm_template=None,
    expect_string=None, read_timeout=20) -> dict:
    '''
    Sends one or more commands to a device and retrieves output.

    Args:
        switch (dict): Device configuration
        command_list (str/list): Single command or list of commands
        fsm (bool): Use TextFSM parsing
        fsm_template (str): Path to FSM template file
        expect_string (str): String to expect in output
        read_timeout (int): Timeout in seconds (default: 20)

    Returns:
        dict: Contains device name, host, command output, device type
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
                        expect_string=expect_string,
                        delay_factor=5, read_timeout=read_timeout))
                if expect_string:
                    try:
                        switch_output.append(
                            connection.send_command(
                                '\n', delay_factor=5, read_timeout=20))
                    except:
                        pass

    except AttributeError:
        logging.warning(f"Could not connect to {switch['host']}")
        return {'name': False, 'output': switch['host']}
    except netmiko.ReadTimeout:
        logging.warning(f"{switch['host']} timed out")
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
    switch_list, command_list, fsm=False, fsm_template=None,
    expect_string=None, read_timeout=20) -> list:
    '''
    Sends commands to multiple devices in parallel (max 24 workers).

    Args:
        switch_list (list): List of device configurations
        command_list (str/list): Commands to send
        fsm (bool): Use TextFSM parsing
        fsm_template (str): FSM template file
        expect_string (str): Expected output string
        read_timeout (int): Timeout in seconds

    Returns:
        list: Results from each device
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
            [expect_string] * repeat,
            [read_timeout] * repeat)

    return list(switch_list_output)


def switch_send_reload(
    switch, delay=None, cancel=False) -> dict:
    '''
    Sends reload command to a device.

    Args:
        switch (dict): Device configuration
        delay (int, optional): Delay in minutes before reload
        cancel (bool): Cancel pending reload if True

    Returns:
        dict: Device name, host, reload output, device type
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
                        command, expect_string="Proceed with reload",
                        delay_factor=5, read_timeout=20))
                switch_output.append(
                    connection.send_command(
                        '\n', delay_factor=5, read_timeout=20))
            if cancel:
                switch_output.append(
                    connection.send_command(
                        'reload cancel', delay_factor=5, read_timeout=20))
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
        'device_type': switch['device_type']}


def switch_list_send_reload(
    switch_list, delay=None, cancel=False) -> list:
    '''
    Sends reload command to multiple devices in parallel.

    Args:
        switch_list (list): List of device configurations
        delay (int, optional): Delay in minutes before reload
        cancel (bool): Cancel pending reloads

    Returns:
        list: Results from each device
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


def switch_config_file(switch, configuration, read_timeout=180) -> dict:
    '''
    Applies configuration file or commands to a device and saves.

    Args:
        switch (dict): Device configuration
        configuration (str/list): Config file path or list of commands
        read_timeout (int): Timeout in seconds (default: 180)

    Returns:
        dict: Device name, output, diff output, device type
    '''

    try:
        with switch_connect(switch) as connection:
            if isinstance(configuration, list):
                switch_output = connection.send_config_set(configuration, read_timeout=read_timeout)
            else:
                switch_output = connection.send_config_from_file(configuration, read_timeout=read_timeout)

            switch_output_diff = f'{connection.find_prompt()}\n'
            if switch['device_type'] == 'cisco_nxos':
                sh_diff = 'sh run diff'
            else:
                sh_diff = 'sh archive config differences'
            switch_output_diff += f'{connection.send_command(sh_diff, read_timeout=60)}'
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
    except Exception as e:
        logging.warning(f"catch all - {e} for {switch['host']}")
        return {'name': False, 'output': switch['host']}

    return {
        'name': switch['host'],
        'output': switch_output,
        'diff': switch_output_diff,
        'device_type': switch['device_type']}


def switch_list_config_file(
    switch_list, config_file, log_file_name) -> None:
    '''
    Applies config to multiple devices and logs results with diffs.

    Args:
        switch_list (list): List of device configurations
        config_file (str): Path to configuration file
        log_file_name (str): Base name for output log files

    Output: Creates dated log files in logs/network/
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


def format_device_list(
    device_list, user, pwd=None, device_type='autodetect') -> list:
    '''
    Formats a list of devices based on IPs or a dict of host and device type.

    Args:
        device_list (str/list): IPs or device dicts
        user (str): Username
        pwd (str, optional): Password. Prompts if not provided.
        device_type (str): Device type (default: autodetect)

    Returns:
        list: Formatted device configs ready for connection
    '''
    if not pwd:
        pwd = verify_pwd(user)
    if isinstance(pwd, bytes):
        pwd = base64.b85decode(pwd).decode('utf-8')
    if isinstance(device_list, str):
        device_list = [device_list]

    device_template = {
        'username': user,
        'password': pwd,
        'fast_cli': False}

    for index, device in enumerate(device_list):
        device_format = device_template.copy()
        if isinstance(device, dict):
            device_format.update(device)
            if 'device_type' not in device_format.keys():
                device_format['device_type'] = device_type
        else:
            device_format['device_type'] = device_type
            device_format['host'] = device

        device_list[index] = device_format

    return device_list


def format_site_yaml(
    site_code, user, pwd=None, filter_group=None, filter_device_type=None,
    filter_location=None, filter_role=None, filter_names=None) -> list:
    '''
    Formats site yaml file into list of devices ready for connection functions.

    Args:
        site_code (str): Site code folder name
        user (str): Username
        pwd (str, optional): Password
        filter_group/device_type/location/role/names: Optional filters

    Returns:
        list: Formatted device configs matching filters
    '''
    if not pwd:
        pwd = verify_pwd(user)
    if filter_names:
        if not isinstance(filter_names, list):
            filter_names = [filter_names]

    device_list = file_loader(
        f'site_info/{site_code}/{site_code}.yml')['Switchlist']

    results = []
    for device in device_list:
        searched_group = True if not filter_group else filter_group in device['groups']
        searched_location = True if not filter_location else filter_location == device['data']['location']
        searched_role = True if not filter_role else filter_role == device['data']['role']
        searched_name = True if not filter_names else device['hostname'] in filter_names
        searched_type = True if not filter_device_type else filter_device_type == device['data']['device_type']

        if (searched_group and searched_location and
            searched_role and searched_name and searched_type):
            results.append({
                'host': device['host'],
                'device_type': device['data']['device_type']})

    return format_device_list(results, user, pwd=pwd)


def search_within_list(
    search_value, search_list, search_key):
    '''
    Searches list of dicts for value in specified key.

    Args:
        search_value: Value to find
        search_list (list): List of dictionaries
        search_key (str): Dictionary key to search

    Returns:
        dict/bool: Matching dict or False if not found
    '''
    for search_list_item in search_list:
        if search_list_item[search_key] == search_value:
            return search_list_item
    return False


def prompt_yes_no(prompt_text) -> bool:
    '''
    Prompts user for yes/no confirmation (case-insensitive).

    Args:
        prompt_text (str): Prompt message

    Returns:
        bool: True if 'y', False otherwise
    '''
    yes_no = input(f'{prompt_text} -> ').lower()[:1]

    return True if yes_no == 'y' else False


def file_loader(file_load, file_lines=None) -> list:
    '''
    Loads YAML, JSON, TextFSM, or text file into Python objects.

    Args:
        file_load (str): File path (.yaml, .json, .fsm, .txt)
        file_lines (bool): Strip newlines from text files if True

    Returns:
        list/dict: File contents as appropriate type
    '''
    with open(file_load, 'r') as file_info:
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
    file_name, file_dir, data, new_line=False,
    file_extension='txt', override=False) -> None:
    '''
    Creates YAML, JSON, or text file with automatic dir creation.

    Args:
        file_name (str): Filename without extension
        file_dir (str): Directory path (auto-created)
        data: Content to write
        new_line (bool): Add newlines between list items
        file_extension (str): File type (yaml, json, txt, crt, key, ini)
        override (bool): Overwrite existing file
    '''
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
        elif file_extension in ['txt', 'ini', 'crt', 'key']:
            if new_line:
                data_file.writelines(line + '\n' for line in data)
            else:
                data_file.writelines(data)


def ping(host, attempts='3'):
    '''
    Pings a single host (platform-aware: Windows vs Unix).

    Args:
        host (str): IP or hostname
        attempts (str): Number of ping attempts (default: 3)

    Returns:
        str: Host if unreachable (bool: False if reachable)
    '''
    suffix = '-n' if system().lower()=='windows' else '-c'
    results = call(
        ['ping', suffix, attempts, host], stdout=DEVNULL)

    return host if results!=0 else False


def ping_list(host_list, attempts='3') -> list:
    '''
    Pings multiple hosts in parallel (max 30 workers).

    Args:
        host_list (list): List of IPs/hostnames
        attempts (str): Number of attempts per host

    Returns:
        list: Hosts that are NOT pingable
    '''
    if not isinstance(host_list, list):
        host_list = [host_list]

    with ThreadPoolExecutor(max_workers=30) as pool:
        ping_output = pool.map(
            ping, host_list,
            attempts * len(host_list))

    not_pingable = set()
    for entry in list(ping_output):
        if entry:
            not_pingable.add(entry)

    return list(not_pingable)


# yaml offical fix
class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(IndentDumper, self).increase_indent(flow, False)


if __name__ == "__main__":
    pass
