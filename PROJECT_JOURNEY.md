# NetDevOps 工具箱项目演进日志

> 记录每一次。
## 2026年1月1日：装饰器（重试机制）和新增API模块
- **优化目标**：为函数`backup.py`和`api_checker.py`增加容错率
- **技术**：
  - 1.从`typling`模块中引入了类型注解：`Dict, Any, Optional，Callable`等等
  - 2.API模块中定义了类（可调用）
- **具体改动**：
  - 1.在API模块里定义查寻云端服务器的函数，和查询设备的函数
  - 2.在`backup.py`模块里引入装饰器，增加容错率
- **学到的知识**：
  - 1.Python里，一切皆对象，装饰器和对应的函数对象息息相关
  - 2.`raise`的传递对象只有一个,当前执行 raise 语句的函数的「直接调用方」，简单说：“谁调用我，我就把异常传给谁”
  - 3.位置参数和关键字参数的区别
  - 4.`*args`,`**kwargs`:前者收集位置参数，解包可迭代对象。后者收集关键字参数，解包只能是字典
  - 5.`delay:.1f`:将delay这个浮点数格式化为保留1位小数的字符串
- **提交哈希**：`5f2d410  `（代码回溯：git checkout `5f2d410 ` ,git checkout --detach `5f2d410 `，git checkout main（取消回溯））

## 2026年1月3日：引入单元测试
- **优化目标**：为核心函数 `read_devices_yml` 增加质量保障,方便测试呗
- **技术**：
  - 1.使用了`pytest`单元测试工具
- **具体改动**：
  - 1.在`test_device_reader.py`和`health_check.py`开头添加`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`；
  - 2.将脚本所在目录插入`sys.path`首位，确保优先搜索项目内模块。
- **学到的知识**：
  - 1.`sys.path`的搜索顺序决定模块优先级,并且他是运行的时候，才会查询目录，默认是查询运行脚本时当前目录
  - 2.`pytest -v`会查询子文件夹，有递归。`pytest -v -no-recyrseondirs`禁用递归仅当前目录
- **提交哈希**：`3bb695d `（代码回溯：git checkout `3bb695d` ,git checkout --detach `3bb695d`，git checkout main（取消回溯））

## 2026年1月2日：重构日志系统，实现统一配置模块
- **优化目标**：增加日志器
- **技术**：
  - 1.使用Python标准库`logging`
- **具体改动**：
  - 1.创建`log_setup.py`，封装日志配置，替换`print`语句；
- **学到的知识**：
  - 1.在`log_setuo.py` 里定义的日志器函数，日志器的名字是自定义的，`.log`文件也是自定义的，自己想更改的话，需要在其他脚本自行设置
  - 2.在其他函数导入模块的话，则会执行顶层代码，可能会导致也用了默认的日志器，会多一个`.log`文件
  - 3.日志重复打印，原因是`logger.propagate`默认值为`True`，需手动设为`False`；
- **提交哈希**：`0c75e8b`（代码回溯：git checkout `0c75e8b`，git checkout --detach `0c75e8b`，git checkout main（取消回溯））
