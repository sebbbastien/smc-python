#### smc-python

Python based library to provide basic functions to interact with the Stonesoft Management Center API.

Currently it provides basic functionality to manipulate object data stored on the SMC. It is working towards having a command line
front end to ease interaction from automated tools such as Chef/Puppet or do automated deployments into virtual and cloud environments.

##### Getting Started

Installing package

use pip

`pip git+https://github.com/gabstopper/smc-python.git`

download the latest tarball: [smc-python](https://github.com/gabstopper/smc-python/archive/master.zip), unzip and run

`python setup.py install`

##### Testing

Included is a test.py script that has several examples for manipulating data using the SMC api.

##### Basics

Before any commands are run, you must obtain a login session. Once commands are complete, call smc.logout() to remove the active session.

```python
import smc

smc.login('http://1.1.1.1:8082', 'EiGpKD4QxlLJ25dbBEp20001')
....do stuff....
smc.logout()
```

Once a valid session is obtained, it will be re-used for each operation performed. 

###### Creating/removing a host record
```python
smc.create_host('ami', '1.1.1.2')
smc.remove('ami')		#remove host named 'ami'
smc.remove('agroup')	#remove group
smc.remove('myfw')		#remove firewall instance
```

###### Create group and add members
```python
smc.create_group('group_with_no_members')
smc.create_host('ami', '1.1.1.1')
smc.create_host('ami2', '2.2.2.2')
smc.create_group('anewgroup', ['ami','ami2']) #group with member list
```

###### Create / remove a single_fw instance
```python
smc.create_single_fw('myfw', '172.18.1.5', '172.18.1.0/24', dns='5.5.5.5', fw_license=True)
time.sleep(5)
smc.remove_single_fw('myfw')
```
get_element(name, obj_type=None, use_name_field=True):
###### Example of using a search filter 
```python
smc.get_element('myobject')  		#Search for element named 'myobject', match on 'name' field (looks at all object types)
smc.get_element('myobject', 'host')	#Search for host element named 'myobject'; match on 'name' field
smc.get_element('myobject', 'host', False)	#Search for host element/s with 'myobject' somewhere in the object definition
```
