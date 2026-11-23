import sys
from pathlib import Path
import xml.etree.ElementTree as ET
p = Path('/var/tmp/many-t0-20261028/evidence')
for name in sys.argv[1:]:
    root = ET.parse(p / (name + '.xml')).getroot()
    for case in root.iter('testcase'):
        problems = [*case.findall('failure'), *case.findall('error')]
        for problem in problems:
            print(case.attrib['classname'] + '::' + case.attrib['name'])
            print(problem.attrib.get('message', '')[:1400])
