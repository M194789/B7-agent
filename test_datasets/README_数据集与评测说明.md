# 多平台考核数据整合测试集

本目录保留原有成绩合成数据及其标准答案，覆盖 CSV、TSV、XLSX。

- `step1_smoke/`：8 行输入、2 行重复、6 行输出，无待复核事项。
- `step2_levels/level1_easy/`：跨平台去重、同名不同学号、考核项目与批次隔离。
- `step2_levels/level2_medium/`：跨格式、明确满分折算、成绩与姓名冲突、缺失学号、非数值成绩。
- `step2_levels/level3_hard/`：陌生表头、越界分数、前导零、缺失业务标识与多平台冲突。

运行：`.venv/Scripts/python.exe test_datasets/evaluate_datasets.py`。
或在工作台“成绩整合”上传对应级别的成绩文件。

这些是固定合成样例，用于回归与边界检查，不代表学校实际数据准确率。困难级中陌生表头需要先确认映射，评测脚本会显式提供映射再检查归并层。
