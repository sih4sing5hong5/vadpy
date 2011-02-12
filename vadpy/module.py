import os
import logging 
import subprocess

from . import common
from .element import Element, LITTLE_ENDIAN
from .error import VADpyError, MissingArgumentError
from .options import Option, bool_parser, split_parser
from .labels import Labels, extend_sections

log = logging.getLogger(__name__)


class ModuleMeta(type):
    def __new__(meta, classname, bases, class_dict):
        for item in class_dict:                    
            attr = class_dict[item]
            if isinstance(attr, Option):
                attr.module = classname.lower() # add module's name to option                
                if not attr.name:
                    attr.name = item
        return type.__new__(meta, classname, bases, class_dict)

    def __str__(cls):
        shelp = 'VADpy module {0}\n{1}\n' \
                'Options:\n{2:<20}Description'.format(cls.__name__ , 
                                                      str(cls.__doc__),
                                                      'Name')
        options = (objattr for objattr in (getattr(cls, attr) for attr in dir(cls))
                   if isinstance(objattr, Option))

        for opt in options: 
            shelp += '\n{0:<20}{1}'.format(opt.name, opt.description)
                                           
        return shelp


class Module(object):
    __metaclass__ =  ModuleMeta
    author = ''
    version = ''

    def __init__(self, vadpy, options):
        """Put all options validation here"""
        self.vadpy = vadpy
        self.settings = vadpy.settings
        self.name = self.__class__.__name__.lower()

        # == setup options == # 
        # get all options defined in class
        for attr in dir(self.__class__): # because we must iterate through all child classes
            objattr = getattr(self.__class__, attr)
            if type(objattr) == Option: # option found
                option = objattr
                name = option.name or attr
                if name in options:
                    setattr(self, attr, option.parse(options[name])) # replace Option object with value
                else:
                    raise MissingArgumentError(option.module, name)

    def __del__(self):
        pass
    
    def run(self):
        log.info('Running {0}'.format(self.__class__.__name__))

    def format_path(self, path, **kwargs):
        """Formats path via static and dynamic format arguments

        The static arguments are built from settings.format_args
        The dynamic arguments are built from module's arguments
        """
        format_args = {'modname' : self.__class__.__name__, 
                       }
        format_args.update(self.vadpy.settings.format_args)
        format_args.update(kwargs)             
        return os.path.abspath( path.format(**format_args) )

            
class DBModule(Module):
    source_name = Option('source-name', description = "Element's source name")
    source_dir = Option('source-dir', description = 'Source directory (relatively to root dir)')
    gt_dir = Option('gt-dir', description = 'Ground Truth directory (relatively to root dir)')    
    dataset = Option(description = 'The dataset path format attribute (see source_dir and gt_dir)')    
    re = Option(description = 'Reqular expression files filter')

    def __init__(self, vadpy, options):
        super(DBModule, self).__init__(vadpy, options)
        self.source_dir = self.format_path(self.source_dir, 
                                           dataset = self.dataset)
        self.gt_dir = self.format_path(self.gt_dir, 
                                       dataset = self.dataset)

    def elements_from_dirs(self, source_name, source_dir, gt_dir, flags, *regexps):
        """Create elements by finding data files and corresponding gt files in given directories
        
        This method is a helper for classes that inherit from DBModule
        """
        assert source_name, 'Source name cannot be blank'
        elements = []
        source_files = common.listdir(source_dir, self.re, *regexps)
        gt_files = common.listdir(gt_dir, self.re, *regexps)

        for source_file in source_files:
            source_file_path = os.path.join(source_dir, source_file)
            gt_file_path = os.path.join(gt_dir, source_file)
            if os.path.isdir(source_file_path):
                continue
            if source_file in gt_files:
                elements.append(
                    Element(source_name,
                            source_file_path, 
                            gt_file_path,
                            flags)
                    )
            else:
                raise VADpyError('Cannot find a GT file for corresponding source file {0}'.format(source_file))
        return elements

    
class IOModule(Module):
    action = Option()
    frame_len = Option('frame-len', float)
    labels_attr = Option('labels-attr', 
                         description = 'Read/Write GT labels from/to defined element\'s attribute containing Labels object. ' \
                                       'In most cases the value will be: gt_labels or vad_labels ' )
    path_attr = Option('path-attr', 
                       description = 'Read/Write data GT labels from/to defined element\'s attribute containing a valid path. ' \
                                     'In most cases the value will be: gt_path or vout_path')

    def __init__(self, vadpy, options):
        super(IOModule, self).__init__(vadpy, options)

    def run(self):
        super(IOModule, self).run()
        if self.action == 'write':
            for element in self.vadpy.pipeline:
                labels = getattr(element, self.labels_attr)
                setattr(labels, 'frame_len', self.frame_len) # settings frame-len is crucial!
    def read(self, path):
        log.debug(('Reading {0}').format(path))

    def write(self, data, path):
        log.debug('Writing to {0}'.format(path))
        common.makedirs( os.path.dirname(path) )


class GenericIOModuleBase(IOModule):
    """A IO Module's base class with generic run() method

    Run() uses current action according to labels_attr and path_attr options. 
    """        
    def run(self):
        super(GenericIOModuleBase, self).run()
        
        if self.action == 'read':
            for element in self.vadpy.pipeline:                
                path = getattr(element, self.path_attr)
                labels = Labels(extend_sections(element, self.read(path), self.frame_len),
                                self.frame_len)

                setattr(element, self.labels_attr, labels)
        elif self.action == 'write':
            for element in self.vadpy.pipeline:
                path = getattr(element, self.path_attr)
                labels = getattr(element, self.labels_attr)
                self.write(labels, path)


class VADModule(Module):
    """Base class for all types of VAD modules"""
    voutdir = Option(description = 'VAD output directory')
    outpath = Option(description = 'Output path template (using Element and Module format arguments)')
    overwrite = Option(parser = bool_parser, 
                       description = 'Indicates if the module must overwrite existing VAD output')
    # filename corresponds to source_path's filename (template)
    def __init__(self, vadpy, options):
        super(VADModule, self).__init__(vadpy, options)

    def run(self):
        super(VADModule, self).run()
        for element in self.vadpy.pipeline:                            
            element.vout_path = self._get_vout_path(element)           
            common.makedirs( os.path.dirname(element.vout_path) )      # create output paths' dirs

    def _get_vout_path(self, element, **kwargs):
        """The method returns an output path for current VAD executable (The path is based on VADpy's configuration)

        This method can be effectively extended by sub classes. 
        Arguments:
        element - element whose vout_path should be generated       
        kwargs  - additional keyword arguments to use while formatting
        """        
        return self.format_path(self.outpath, 
                                voutdir = self.voutdir, 
                                **dict(element.format_args,**kwargs))
                                

        
class SimpleVADModuleBase(VADModule):
    """Basic wrapper for VADModule

    SimpleCodecModule is a basic wrapper to standalone VAD executables (e.g. G.729, ARM)
    that require no training and can produce a single VAD output file by processing
    a single input file. 
    """    
    exec_path = Option('exec-path', parser = os.path.abspath)

    def __init__(self, vadpy, options):
        super(SimpleVADModuleBase, self).__init__(vadpy, options)
        self._cmd = '{execpath} {vadoptions} {in_path} {out_path}' # command-line to run VAD

    def _get_exec_options(self, element):
        """Return VADModule-specific executable options to use before and after commmand-line arguments"""
        return [], []
      
    def run(self):
        super(SimpleVADModuleBase, self).run() 

        for element in self.vadpy.pipeline:
            if not self.overwrite and os.path.exists(element.vout_path):
                log.debug('File already exists: {0}'.format(element.vout_path))
                continue

            # execution options list
            options_before_args, options_after_args = self._get_exec_options(element)

            lstrun = [self.exec_path,]
            lstrun.extend(options_before_args)
            lstrun.append(element.source_path)
            lstrun.append(element.vout_path)
            lstrun.extend(options_after_args)

            log.debug('Executing VAD: {0}'.format(lstrun))

            proc = subprocess.Popen(lstrun, 
                                    close_fds = True,
                                    stdin = subprocess.PIPE, 
                                    #stdout = subprocess.PIPE,
                                    stderr = subprocess.PIPE, 
                                    )
            stdoutdata, stderrdata = proc.communicate()
            assert not stderrdata, stderrdata



class MatlabVADModuleBase(VADModule):
    """MATLAB-based VADs wrapper for VADModule"""
    bin = Option(description = 'A path to matlab binary')
    mopts = Option(description = 'Matlab options and arguments')
    engine = Option(description = 'A path to VADpy-to-MATLAB engine\'s function name')
    scriptdir = Option(description = 'A directory in which VAD algorithms scripts are located; Matlab working directory')
    filecount = Option(description = 'Amount of files to be passed to Matlab engine at a time', 
                       parser = int)

    def __init__(self, vadpy, options):
        super(MatlabVADModuleBase, self).__init__(vadpy, options)
        assert self.filecount > 0, 'Filecount must be > 0'
        self._execargs = {'engine' : self.engine, 
                          '__bracket__' : '"',
                          }

        self._execlist = ['{engine}', 
                          "'{endianness}'", 
                          "'{in_paths}'",
                          "'{out_paths}'",
                          "'{gt_paths}'"
                          ]
    
    def run(self):
        super(MatlabVADModuleBase, self).run()
        pipeline = self.vadpy.pipeline

        self._execlist = ['-r', '{__bracket__}'] + self._execlist + [' {__bracket__}']
    
        # set internal flags for matlab engine        
        assert pipeline.is_monotonic(), "Cannot process non-monotonic pipeline (elements' flags differ"
        
        for elements in pipeline.slice(self.filecount):  # slice generator is used(!)
            elements = [elem for elem in elements
                        if self.overwrite or not os.path.exists(elem.vout_path)]
            if not elements:
                return 

            self._execargs['endianness'] = elements[0].flags & LITTLE_ENDIAN and 'l' or 'b'
            
            for elem in elements:
                in_paths = ';'.join(elem.source_path for elem in elements)
                gt_paths = ';'.join(elem.gt_path for elem in elements)
                out_paths = ';'.join(elem.vout_path for elem in elements)
                               
            self._execargs['in_paths'] = in_paths
            self._execargs['gt_paths'] = gt_paths
            self._execargs['out_paths'] = out_paths
            
            sexec = ' '.join(self._execlist)
            sexec = sexec.format(**self._execargs)
            lstrun = [self.bin, self.mopts, sexec]

            log.debug('Starting MATLAB-based codec:\t {0} {1} {2}'.format(self.bin, self.mopts, sexec))
            
            proc = subprocess.Popen(lstrun, 
                                    cwd = self.scriptdir, 
                                    close_fds = True,
                                    stdin = subprocess.PIPE, 
                                    stdout = subprocess.PIPE,
                                    stderr = subprocess.PIPE, 
                                    )
            stdoutdata, stderrdata = proc.communicate()
            assert not stderrdata, stderrdata


class CompareModule(Module):
    """Base module for comparing elements' labels (and printing the output to stdout)
    """
    inputs = Option(parser = split_parser, 
                    description = 'Input labels\' attributes separated by ",". '\
                                  'In most cases those are gt_labels,vad_labels')
    sep_sources = Option('sep-sources', bool_parser, 'Treat files from every source separately.')

    def __init__(self, vadpy, options):
        super(CompareModule, self).__init__(vadpy, options)
        assert all(self.inputs), 'Inputs are empty'

    def run(self):
        super(CompareModule, self).run()
    
