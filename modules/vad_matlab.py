import logging 

from vadpy.module import MatlabVADModuleBase
from vadpy.element import LITTLE_ENDIAN, BIG_ENDIAN
from vadpy.options import Option

log = logging.getLogger(__name__)


class VADMatlab(MatlabVADModuleBase):
    script = Option(description = 'VAD function name')
    fread = Option(description = 'Length of a signal in each fread iteration (in seconds)')
    args = Option(description = 'Additional arguments to be passed to matlab script')

    def __init__(self, vadpy, options):
        super(VADMatlab, self).__init__(vadpy, options)
        assert self.filecount > 0, 'Filecount must be > 0'

    def run(self):
        self._execargs['script'] = self.script
        self._execargs['fread_len'] = self.fread
        self._execargs['vad_args'] = self.args

        self._execlist = ['{engine}', 
                          "'{script}'",
                          "'{vad_args}'",
                          "'{endianness}'", 
                          "{fread_len}",
                          "'{in_paths}'",
                          "'{out_paths}'",
                          ]
                          
        super(VADMatlab, self).run()
        
