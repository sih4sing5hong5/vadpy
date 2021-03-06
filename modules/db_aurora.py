import os

from vadpy import common
from vadpy.module import DBModule
from vadpy.element import Element, BIG_ENDIAN, FS_8000, BPS_16
from vadpy.options import StrictOption, split_parser

import logging 
log = logging.getLogger(__name__)

class DBAURORA(DBModule):
    """AURORA2 corpus module"""
    env = StrictOption(parser = split_parser, description = 'Environment numbers separated by ","', 
                       values = ['1','2','3','4'])

    snr = StrictOption(parser = split_parser, description = 'SNR rates separated by ","', 
                       values = ['C','20','15','10', '5', '0', '-5'])

    FLAGS = BIG_ENDIAN | FS_8000 | BPS_16
    
    def __init__(self, vadpy, options):
        super(DBAURORA, self).__init__(vadpy, options)
        
    def run(self):
        super(DBAURORA, self).run()
        elements = []
        for env in self.env:
            for snr in self.snr:                             
                source_file_name = 'N{0}_SNR{1}'.format(env, snr)
                source_file_path = os.path.join(self.source_dir, source_file_name)

                if self.dataset.startswith('TRAIN'):
                    gt_file_path = os.path.join(self.gt_dir, source_file_name)
                elif self.dataset.startswith('TEST'):
                    gt_file_path = os.path.join(self.gt_dir, 'N{0}'.format(env))

                elements.append(
                    Element('{0}/{1}'.format(self.source_name, self.dataset),
                            source_file_path, 
                            gt_file_path,
                            self.FLAGS)
                    )
        self.vadpy.pipeline.add(*elements)
