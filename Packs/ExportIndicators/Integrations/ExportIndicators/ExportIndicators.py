import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *
import json
from flask import Flask, Response, request
from gevent.pywsgi import WSGIServer
from tempfile import NamedTemporaryFile
from typing import Callable, List, Any, cast, Dict, Tuple
from base64 import b64decode
from netaddr import IPAddress, iprange_to_cidrs


class Handler:
    @staticmethod
    def write(msg):
        demisto.info(msg)


''' GLOBAL VARIABLES '''
INTEGRATION_NAME: str = 'Export Indicators Service'
PAGE_SIZE: int = 200
DEMISTO_LOGGER: Handler = Handler()
APP: Flask = Flask('demisto-export_iocs')
CTX_VALUES_KEY: str = 'dmst_export_iocs_values'
CTX_MIMETYPE_KEY: str = 'dmst_export_iocs_mimetype'
FORMAT_CSV: str = 'csv'
FORMAT_TEXT: str = 'text'
FORMAT_JSON_SEQ: str = 'json-seq'
FORMAT_JSON: str = 'json'
CTX_FORMAT_ERR_MSG: str = 'Please provide a valid format from: text,json,json-seq,csv'
CTX_LIMIT_ERR_MSG: str = 'Please provide a valid integer for List Size'
CTX_OFFSET_ERR_MSG: str = 'Please provide a valid integer for Starting Index'
CTX_COLLAPSE_ERR_MSG: str = 'The Collapse parameter can only get the following: 0 - Dont Collapse, ' \
                            '1 - Collapse to Ranges, 2 - Collapse to CIDRS'
CTX_MISSING_REFRESH_ERR_MSG: str = 'Refresh Rate must be "number date_range_unit", examples: (2 hours, 4 minutes, ' \
                                   '6 months, 1 day, etc.)'

DONT_COLLAPSE = "Don't Collapse"
COLLAPSE_TO_CIDR = "To CIDRS"
COLLAPSE_TO_RANGES = "To Ranges"

''' HELPER FUNCTIONS '''


def list_to_str(inp_list: list, delimiter: str = ',', map_func: Callable = str) -> str:
    """
    Transforms a list to an str, with a custom delimiter between each list item
    """
    str_res = ""
    if inp_list:
        if isinstance(inp_list, list):
            str_res = delimiter.join(map(map_func, inp_list))
        else:
            raise AttributeError('Invalid inp_list provided to list_to_str')
    return str_res


def get_params_port(params: dict = demisto.params()) -> int:
    """
    Gets port from the integration parameters
    """
    port_mapping: str = params.get('longRunningPort', '')
    err_msg: str
    port: int
    if port_mapping:
        err_msg = f'Listen Port must be an integer. {port_mapping} is not valid.'
        if ':' in port_mapping:
            port = try_parse_integer(port_mapping.split(':')[1], err_msg)
        else:
            port = try_parse_integer(port_mapping, err_msg)
    else:
        raise ValueError('Please provide a Listen Port.')
    return port


def refresh_outbound_context(indicator_query: str, out_format: str, limit: int = 0, offset: int = 0,
                             collapse_ips=DONT_COLLAPSE) -> str:
    """
    Refresh the cache values and format using an indicator_query to call demisto.searchIndicators
    Returns: List(IoCs in output format)
    """
    now = datetime.now()
    iocs = find_indicators_with_limit(indicator_query, limit, offset)  # poll indicators into list from demisto
    out_dict, actual_indicator_amount = create_values_out_dict(iocs, out_format, collapse_ips=collapse_ips)

    # re-polling in case ip collapse caused a lack in results
    while collapse_ips != DONT_COLLAPSE and actual_indicator_amount < limit:
        # from where to start the new poll and how many results should be fetched
        new_offset = len(iocs) + offset + actual_indicator_amount - 1
        new_limit = limit - actual_indicator_amount

        # poll additional indicators into list from demisto
        new_iocs = find_indicators_with_limit(indicator_query, new_limit, new_offset)

        # in case no additional indicators exist - exit
        if len(new_iocs) == 0:
            break

        # add the new results to the existing results
        iocs += new_iocs

        # reformat the output
        out_dict, actual_indicator_amount = create_values_out_dict(iocs, out_format, collapse_ips=collapse_ips)

    out_dict[CTX_MIMETYPE_KEY] = 'application/json' if out_format == FORMAT_JSON else 'text/plain'
    demisto.setIntegrationContext({
        "last_output": out_dict,
        'last_run': date_to_timestamp(now),
        'last_limit': limit,
        'last_offset': offset,
        'last_format': out_format,
        'last_query': indicator_query,
        'current_iocs': iocs
    })
    return out_dict[CTX_VALUES_KEY]


def find_indicators_with_limit(indicator_query: str, limit: int, offset: int) -> list:
    """
    Finds indicators using demisto.searchIndicators
    """
    # calculate the starting page (each page holds 200 entries)
    if offset:
        next_page = int(offset / PAGE_SIZE)

        # set the offset from the starting page
        offset_in_page = offset - (PAGE_SIZE * next_page)

    else:
        next_page = 0
        offset_in_page = 0

    iocs, _ = find_indicators_with_limit_loop(indicator_query, limit, next_page=next_page)

    # if offset in page is bigger than the amount of results returned return empty list
    if len(iocs) <= offset_in_page:
        return []

    return iocs[offset_in_page:limit + offset_in_page]


def find_indicators_with_limit_loop(indicator_query: str, limit: int, total_fetched: int = 0, next_page: int = 0,
                                    last_found_len: int = PAGE_SIZE):
    """
    Finds indicators using while loop with demisto.searchIndicators, and returns result and last page
    """
    iocs: List[dict] = []
    if not last_found_len:
        last_found_len = total_fetched
    while last_found_len == PAGE_SIZE and limit and total_fetched < limit:
        fetched_iocs = demisto.searchIndicators(query=indicator_query, page=next_page, size=PAGE_SIZE).get('iocs')
        iocs.extend(fetched_iocs)
        last_found_len = len(fetched_iocs)
        total_fetched += last_found_len
        next_page += 1
    return iocs, next_page


def ips_to_ranges(ips: list, collapse_ips):
    ip_ranges = []
    ips_range_groups = []  # type:List
    ips = sorted(ips)
    for ip in ips:
        appended = False
        if len(ips_range_groups) == 0:
            ips_range_groups.append([ip])
            continue

        for group in ips_range_groups:
            if IPAddress(int(ip) + 1) in group or IPAddress(int(ip) - 1) in group:
                group.append(ip)
                sorted(group)
                appended = True

        if not appended:
            ips_range_groups.append([ip])

    for group in ips_range_groups:
        # handle single ips
        if len(group) == 1:
            ip_ranges.append(str(group[0]))
            continue

        min_ip = group[0]
        max_ip = group[-1]
        if collapse_ips == COLLAPSE_TO_RANGES:
            ip_ranges.append(str(min_ip) + "-" + str(max_ip))

        elif collapse_ips == COLLAPSE_TO_CIDR:
            moved_ip = False
            # CIDR must begin with and even LSB
            # if the first ip does not - separate it from the rest of the range
            if (int(str(min_ip).split('.')[-1]) % 2) != 0:
                ip_ranges.append(str(min_ip))
                min_ip = group[1]
                moved_ip = True

            # CIDR must end with uneven LSB
            # if the last ip does not - separate it from the rest of the range
            if (int(str(max_ip).split('.')[-1]) % 2) == 0:
                ip_ranges.append(str(max_ip))
                max_ip = group[-2]
                moved_ip = True

            # if both min and max ips were shifted and there are only 2 ips in the range
            # we added both ips by the shift and now we move to the next  range
            if moved_ip and len(group) == 2:
                continue

            else:
                ip_ranges.append(str(iprange_to_cidrs(min_ip, max_ip)[0].cidr))

    return ip_ranges


def create_values_out_dict(iocs: list, out_format: str, collapse_ips=DONT_COLLAPSE) -> Tuple[dict, int]:
    """
    Create a dictionary for output values using the selected format (json, json-seq, text, csv)
    """
    if out_format == FORMAT_JSON:  # handle json separately
        iocs_list = [ioc for ioc in iocs]
        return {CTX_VALUES_KEY: json.dumps(iocs_list)}, len(iocs)
    else:
        ipv4_formatted_indicators = []
        ipv6_formatted_indicators = []
        formatted_indicators = []
        if out_format == FORMAT_CSV and len(iocs) > 0:  # add csv keys as first item
            headers = list(iocs[0].keys())
            formatted_indicators.append(list_to_str(headers))
        for ioc in iocs:
            value = ioc.get('value')
            type = ioc.get('indicator_type')
            if value:
                if out_format == FORMAT_TEXT:
                    if type == 'IP' and collapse_ips != DONT_COLLAPSE:
                        ipv4_formatted_indicators.append(IPAddress(value))
                    elif type == 'IPv6' and collapse_ips != DONT_COLLAPSE:
                        ipv6_formatted_indicators.append(IPAddress(value))
                    else:
                        formatted_indicators.append(value)
                elif out_format == FORMAT_JSON_SEQ:
                    formatted_indicators.append(json.dumps(ioc))
                elif out_format == FORMAT_CSV:
                    # wrap csv values with " to escape them
                    values = list(ioc.values())
                    formatted_indicators.append(list_to_str(values, map_func=lambda val: f'"{val}"'))

        if len(ipv4_formatted_indicators) > 0:
            ipv4_formatted_indicators = ips_to_ranges(ipv4_formatted_indicators, collapse_ips)
            formatted_indicators.extend(ipv4_formatted_indicators)

        if len(ipv6_formatted_indicators) > 0:
            ipv6_formatted_indicators = ips_to_ranges(ipv6_formatted_indicators, collapse_ips)
            formatted_indicators.extend(ipv6_formatted_indicators)

    return {CTX_VALUES_KEY: list_to_str(formatted_indicators, '\n')}, len(formatted_indicators)


def get_outbound_mimetype() -> str:
    """Returns the mimetype of the export_iocs"""
    ctx = demisto.getIntegrationContext().get('last_output')
    return ctx.get(CTX_MIMETYPE_KEY, 'text/plain')


def is_request_change(limit, offset, out_format=FORMAT_TEXT, last_update_data={}) -> bool:
    """ Checks for changes in the request params

    Args:
        limit (int): limit on how many indicators should be exported.
        offset (int): the index of the indicator from which the list should be exported.
        out_format (str): the requested output format.
        last_update_data (dict): the cached params for the last request.

    Returns:
        bool. True if limit/offset/out_format params have changed since the last request, False otherwise.
    """
    last_limit = last_update_data.get('last_limit')
    last_offset = last_update_data.get('last_offset')
    last_format = last_update_data.get('last_format')

    return out_format != last_format or limit != last_limit or offset != last_offset


def get_outbound_ioc_values(on_demand, limit, offset, indicator_query='', out_format=FORMAT_TEXT, last_update_data={},
                            cache_refresh_rate=None, collapse_ips=DONT_COLLAPSE) -> str:
    """
    Get the ioc list to return in the list
    """
    last_update = last_update_data.get('last_run')
    last_query = last_update_data.get('last_query')
    current_iocs = last_update_data.get('current_iocs')

    # on_demand ignores cache
    if on_demand:
        if is_request_change(limit, offset, out_format, last_update_data):
            values_str = get_ioc_values_str_from_context(current_iocs, out_format, limit, offset)

        else:
            values_str = get_ioc_values_str_from_context()

    else:
        if last_update:
            # takes the cache_refresh_rate amount of time back since run time.
            cache_time, _ = parse_date_range(cache_refresh_rate, to_timestamp=True)
            if last_update <= cache_time or is_request_change(limit, offset, out_format, last_update_data) or \
                    indicator_query != last_query:
                values_str = refresh_outbound_context(indicator_query, out_format, limit=limit, offset=offset,
                                                      collapse_ips=collapse_ips)
            else:
                values_str = get_ioc_values_str_from_context()
        else:
            values_str = refresh_outbound_context(indicator_query, out_format, limit=limit, offset=offset,
                                                  collapse_ips=collapse_ips)

    return values_str


def get_ioc_values_str_from_context(iocs=None, new_format: str = FORMAT_TEXT,
                                    limit: int = 10000, offset: int = 0) -> str:
    """
    Extracts output values from cache
    """
    if iocs:
        if offset > len(iocs):
            return ''

        iocs = iocs[offset: limit + offset]
        returned_dict, _ = create_values_out_dict(iocs, new_format)
        current_cache = demisto.getIntegrationContext()
        current_cache['last_output'] = returned_dict
        demisto.setIntegrationContext(current_cache)

    else:
        returned_dict = demisto.getIntegrationContext().get('last_output', {})

    return returned_dict.get(CTX_VALUES_KEY, '')


def try_parse_integer(int_to_parse: Any, err_msg: str) -> int:
    """
    Tries to parse an integer, and if fails will throw DemistoException with given err_msg
    """
    try:
        res = int(int_to_parse)
    except (TypeError, ValueError):
        raise DemistoException(err_msg)
    return res


def validate_basic_authentication(headers: dict, username: str, password: str) -> bool:
    """
    Checks whether the authentication is valid.
    :param headers: The headers of the http request
    :param username: The integration's username
    :param password: The integration's password
    :return: Boolean which indicates whether the authentication is valid or not
    """
    credentials: str = headers.get('Authorization', '')
    if not credentials or 'Basic ' not in credentials:
        return False
    encoded_credentials: str = credentials.split('Basic ')[1]
    credentials: str = b64decode(encoded_credentials).decode('utf-8')
    if ':' not in credentials:
        return False
    credentials_list = credentials.split(':')
    if len(credentials_list) != 2:
        return False
    user, pwd = credentials_list
    return user == username and pwd == password


''' ROUTE FUNCTIONS '''


def get_request_args(params):
    limit = try_parse_integer(request.args.get('n', params.get('list_size', 10000)), CTX_LIMIT_ERR_MSG)
    offset = try_parse_integer(request.args.get('s', 0), CTX_OFFSET_ERR_MSG)
    out_format = request.args.get('v', params.get('format', 'text'))
    query = request.args.get('q', params.get('indicators_query'))
    collapse_ips = request.args.get('tr', params.get('collapse_ips', DONT_COLLAPSE))

    if collapse_ips is not None and collapse_ips not in [DONT_COLLAPSE, COLLAPSE_TO_CIDR, COLLAPSE_TO_RANGES]:
        collapse_ips = try_parse_integer(collapse_ips, CTX_COLLAPSE_ERR_MSG)
        if collapse_ips == 0:
            collapse_ips = DONT_COLLAPSE

        elif collapse_ips == 1:
            collapse_ips = COLLAPSE_TO_RANGES

        elif collapse_ips == 2:
            collapse_ips = COLLAPSE_TO_CIDR

    # prevent given empty params
    if len(query) == 0:
        query = params.get('indicators_query')

    if len(out_format) == 0:
        out_format = params.get('format', 'text')

    if out_format not in ['text', 'json', 'json-seq', 'csv']:
        raise DemistoException(CTX_FORMAT_ERR_MSG)

    return limit, offset, out_format, query, collapse_ips


@APP.route('/', methods=['GET'])
def route_list_values() -> Response:
    """
    Main handler for values saved in the integration context
    """
    try:
        params = demisto.params()

        credentials = params.get('credentials') if params.get('credentials') else {}
        username: str = credentials.get('identifier', '')
        password: str = credentials.get('password', '')
        if username and password:
            headers: dict = cast(Dict[Any, Any], request.headers)
            if not validate_basic_authentication(headers, username, password):
                err_msg: str = 'Basic authentication failed. Make sure you are using the right credentials.'
                demisto.debug(err_msg)
                return Response(err_msg, status=401)

        limit, offset, out_format, query, collapse_ips = get_request_args(params)

        values = get_outbound_ioc_values(
            out_format=out_format,
            on_demand=params.get('on_demand'),
            limit=limit,
            offset=offset,
            last_update_data=demisto.getIntegrationContext(),
            indicator_query=query,
            cache_refresh_rate=params.get('cache_refresh_rate'),
            collapse_ips=collapse_ips
        )

        mimetype = get_outbound_mimetype()
        return Response(values, status=200, mimetype=mimetype)

    except Exception as e:
        return Response(str(e), status=400, mimetype='text/plain')


''' COMMAND FUNCTIONS '''


def test_module(args, params):
    """
    Validates:
        1. Valid port.
        2. Valid cache_refresh_rate
    """
    get_params_port(params)
    on_demand = params.get('on_demand', None)
    if not on_demand:
        try_parse_integer(params.get('list_size'), CTX_LIMIT_ERR_MSG)  # validate export_iocs Size was set
        query = params.get('indicators_query')  # validate indicators_query isn't empty
        if not query:
            raise ValueError('"Indicator Query" is required. Provide a valid query.')
        cache_refresh_rate = params.get('cache_refresh_rate', '')
        if not cache_refresh_rate:
            raise ValueError(CTX_MISSING_REFRESH_ERR_MSG)
        # validate cache_refresh_rate value
        range_split = cache_refresh_rate.split(' ')
        if len(range_split) != 2:
            raise ValueError(CTX_MISSING_REFRESH_ERR_MSG)
        try_parse_integer(range_split[0], 'Invalid time value for the Refresh Rate. Must be a valid integer.')
        if not range_split[1] in ['minute', 'minutes', 'hour', 'hours', 'day', 'days', 'month', 'months', 'year',
                                  'years']:
            raise ValueError(
                'Invalid time unit for the Refresh Rate. Must be minutes, hours, days, months, or years.')
        parse_date_range(cache_refresh_rate, to_timestamp=True)
    return 'ok', {}, {}


def run_long_running(params):
    """
    Start the long running server
    :param params: Demisto params
    :return: None
    """
    certificate: str = params.get('certificate', '')
    private_key: str = params.get('key', '')

    certificate_path = str()
    private_key_path = str()

    try:
        port = get_params_port(params)
        ssl_args = dict()

        if (certificate and not private_key) or (private_key and not certificate):
            raise DemistoException('If using HTTPS connection, both certificate and private key should be provided.')

        if certificate and private_key:
            certificate_file = NamedTemporaryFile(delete=False)
            certificate_path = certificate_file.name
            certificate_file.write(bytes(certificate, 'utf-8'))
            certificate_file.close()
            ssl_args['certfile'] = certificate_path

            private_key_file = NamedTemporaryFile(delete=False)
            private_key_path = private_key_file.name
            private_key_file.write(bytes(private_key, 'utf-8'))
            private_key_file.close()
            ssl_args['keyfile'] = private_key_path
            demisto.debug('Starting HTTPS Server')
        else:
            demisto.debug('Starting HTTP Server')

        server = WSGIServer(('', port), APP, **ssl_args, log=DEMISTO_LOGGER)
        server.serve_forever()
    except Exception as e:
        if certificate_path:
            os.unlink(certificate_path)
        if private_key_path:
            os.unlink(private_key_path)
        demisto.error(f'An error occurred in long running loop: {str(e)}')
        raise ValueError(str(e))


def update_outbound_command(args, params):
    """
    Updates the export_iocs values and format on demand
    """
    on_demand = demisto.params().get('on_demand')
    if not on_demand:
        raise DemistoException(
            '"Update exported IOCs On Demand" is off. If you want to update manually please toggle it on.')
    limit = try_parse_integer(args.get('list_size', params.get('list_size')), CTX_LIMIT_ERR_MSG)
    print_indicators = args.get('print_indicators')
    query = args.get('query')
    out_format = args.get('format')
    offset = args.get('offset')
    collapse_ips = args.get('collapse_ips')
    indicators = refresh_outbound_context(query, out_format, limit=limit, offset=offset, collapse_ips=collapse_ips)
    hr = tableToMarkdown('List was updated successfully with the following values', indicators,
                         ['Indicators']) if print_indicators == 'true' else 'List was updated successfully'
    return hr, {}, indicators


def main():
    """
    Main
    """
    params = demisto.params()

    credentials = params.get('credentials') if params.get('credentials') else {}
    username: str = credentials.get('identifier', '')
    password: str = credentials.get('password', '')
    if (username and not password) or (password and not username):
        err_msg: str = 'If using credentials, both username and password should be provided.'
        demisto.debug(err_msg)
        raise DemistoException(err_msg)

    command = demisto.command()
    demisto.debug('Command being called is {}'.format(command))
    commands = {
        'test-module': test_module,
        'eis-update': update_outbound_command
    }

    try:
        if command == 'long-running-execution':
            run_long_running(params)
        else:
            readable_output, outputs, raw_response = commands[command](demisto.args(), params)
            return_outputs(readable_output, outputs, raw_response)
    except Exception as e:
        err_msg = f'Error in {INTEGRATION_NAME} Integration [{e}]'
        return_error(err_msg)


if __name__ in ['__main__', '__builtin__', 'builtins']:
    main()
