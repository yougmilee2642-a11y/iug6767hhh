import os
from meetings.connectors.mock import MockCRM


def connector(c,actor,**kwargs):
    if os.getenv('MEETINGS_BITRIX_ENABLED','0')=='1':
        from meetings.connectors.bitrix24 import Bitrix24Connector
        return Bitrix24Connector(c,actor,**kwargs)
    return MockCRM(c,actor,**kwargs)


def name():return 'bitrix24' if os.getenv('MEETINGS_BITRIX_ENABLED','0')=='1' else MockCRM.name
