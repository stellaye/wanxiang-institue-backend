import logging
import logging.config
import os
from tornado.options import define, options

# 定义日志配置
def setup_logging():
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
            },
            'detailed': {
                'format': '[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] [%(module)s.%(funcName)s] - %(message)s'
            },
            'simple': {
                'format': '[%(levelname)s] %(message)s'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'simple',
                'stream': 'ext://sys.stdout'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'INFO',
                'formatter': 'standard',
                'filename': os.path.join(log_dir, 'app.log'),
                'maxBytes': 10485760,  # 10MB
                'backupCount': 10,
                'encoding': 'utf8'
            },
            'error_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'ERROR',
                'formatter': 'detailed',
                'filename': os.path.join(log_dir, 'error.log'),
                'maxBytes': 10485760,
                'backupCount': 10,
                'encoding': 'utf8'
            }
        },
        'loggers': {
            '': {  # root logger
                'level': 'INFO',
                'handlers': ['console', 'file', 'error_file']
            },
            'app': {
                'level': 'DEBUG',
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'tornado.access': {
                'level': 'WARNING',
                'handlers': ['file'],
                'propagate': False
            },
            'tornado.application': {
                'level': 'WARNING',
                'handlers': ['file'],
                'propagate': False
            },
            'tornado.general': {
                'level': 'WARNING',
                'handlers': ['file'],
                'propagate': False
            }
        }
    }
    
    logging.config.dictConfig(logging_config)
    return logging.getLogger('app')

# 在main文件中使用
logger = setup_logging()
