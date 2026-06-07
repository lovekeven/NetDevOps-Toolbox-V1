/**
 * 网络拓扑可视化模块（一期增强版）
 * 用 vis.js 画拓扑图，支持扫描、导出、设备详情
 */

class NetworkTopology {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.network = null;
        this.nodes = new vis.DataSet();
        this.edges = new vis.DataSet();
        this.options = {
            physics: {
                enabled: true,
                barnesHut: {
                    gravitationalConstant: -2000,
                    centralGravity: 0.3,
                    springLength: 200,
                    springConstant: 0.04,
                    damping: 0.09
                },
                stabilization: {
                    enabled: true,
                    iterations: 1000,
                    updateInterval: 100
                }
            },
            interaction: {
                hover: true,
                tooltipDelay: 200,
                zoomView: true,
                dragView: true,
                multiselect: true
            },
            nodes: {
                font: {
                    color: '#ffffff',
                    size: 14,
                    face: 'Inter, sans-serif'
                },
                borderWidth: 2,
                shadow: true
            },
            edges: {
                width: 2,
                shadow: true,
                smooth: {
                    type: 'continuous'
                }
            },
            ...options
        };

        this.init();
    }

    init() {
        if (!this.container) {
            console.error(`找不到容器: ${this.containerId}`);
            return;
        }

        // 创建拓扑图画布
        this.network = new vis.Network(
            this.container,
            { nodes: this.nodes, edges: this.edges },
            this.options
        );

        // 绑定事件
        this.bindEvents();

        console.log('拓扑模块初始化完成');
    }

    bindEvents() {
        // 双击节点 -> 触发健康检查
        this.network.on('doubleClick', (params) => {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                this.onNodeDoubleClick(nodeId);
            }
        });

        // 悬停变手势
        this.network.on('hoverNode', () => {
            this.container.style.cursor = 'pointer';
        });
        this.network.on('blurNode', () => {
            this.container.style.cursor = 'default';
        });
    }

    onNodeDoubleClick(nodeId) {
        // 触发健康检查（如果全局定义了的话）
        if (typeof window.healthCheck === 'function') {
            window.healthCheck(nodeId);
        }
    }

    // -----------------------------------------------------------
    // 节点样式配置
    // -----------------------------------------------------------

    getDeviceNodeConfig(device) {
        const { node_id, name, device_type, vendor, status, ip_address } = device;
        const id = node_id || device.id;
        const type = device_type || device.type || 'switch';
        const isOnline = (status || 'online') === 'online';

        // 设备类型样式映射（图标 + 颜色）
        const DEVICE_STYLES = {
            router:   { shape: 'icon', icon: '', color: '#8b5cf6', offline: '#6b7280', size: 40 },
            switch:   { shape: 'icon', icon: '', color: '#3b82f6', offline: '#6b7280', size: 35 },
            firewall: { shape: 'icon', icon: '', color: '#f59e0b', offline: '#6b7280', size: 35 },
            pc:       { shape: 'icon', icon: '', color: '#10b981', offline: '#ef4444', size: 25 },
            server:   { shape: 'icon', icon: '', color: '#6366f1', offline: '#6b7280', size: 30 },
            ap:       { shape: 'icon', icon: '', color: '#10b981', offline: '#ef4444', size: 25 },
            cloud:    { shape: 'icon', icon: '', color: '#3b82f6', offline: '#6b7280', size: 50 },
            printer:  { shape: 'icon', icon: '', color: '#8b5cf6', offline: '#6b7280', size: 25 },
            camera:   { shape: 'icon', icon: '', color: '#f59e0b', offline: '#6b7280', size: 25 },
            phone:    { shape: 'icon', icon: '', color: '#10b981', offline: '#ef4444', size: 25 },
        };

        const style = DEVICE_STYLES[type] || DEVICE_STYLES.switch;

        const icon = {
            face: 'FontAwesome',
            code: style.icon,
            size: Math.round(style.size * 0.8),
            color: isOnline ? style.color : style.offline
        };

        return {
            id: id,
            label: name || id,
            shape: style.shape,
            color: { background: 'transparent', border: 'transparent' },
            icon: icon,
            size: style.size,
            title: this.generateTooltip(device),
            font: {
                color: '#ffffff',
                size: 12,
                strokeWidth: 3,
                strokeColor: '#000000'
            },
            shadow: {
                enabled: true,
                color: 'rgba(0,0,0,0.3)',
                size: 10,
                x: 5,
                y: 5
            }
        };
    }

    generateTooltip(device) {
        const name = device.name || device.node_id || '未知';
        const ip = device.ip_address || device.ip || 'N/A';
        const vendor = device.vendor || 'N/A';
        const type = device.device_type || device.type || 'N/A';
        const status = device.status || 'unknown';
        const layer = device.layer || 'N/A';

        const typeMap = { 'router': '路由器', 'switch': '交换机', 'firewall': '防火墙', 'pc': '终端', 'ap': 'AP' };
        const statusText = status === 'online' ? '✅ 在线' : status === 'offline' ? '❌ 离线' : '❓ 未知';
        const layerMap = { 'core': '核心层', 'aggregation': '汇聚层', 'access': '接入层' };

        return `
            <div style="padding: 10px; background: #1e293b; border-radius: 8px; color: #f1f5f9; min-width: 150px;">
                <div style="font-weight: 600; margin-bottom: 8px; font-size: 14px;">${name}</div>
                <div style="font-size: 12px; color: #94a3b8; line-height: 1.8;">
                    <div>IP: ${ip}</div>
                    <div>厂商: ${vendor}</div>
                    <div>类型: ${typeMap[type] || type}</div>
                    <div>层级: ${layerMap[layer] || layer}</div>
                    <div>状态: ${statusText}</div>
                </div>
            </div>
        `;
    }

    // -----------------------------------------------------------
    // 节点操作
    // -----------------------------------------------------------

    addDeviceNode(device) {
        const config = this.getDeviceNodeConfig(device);
        this.nodes.update(config);
    }

    removeNode(nodeId) {
        this.nodes.remove(nodeId);
    }

    updateNodeStatus(nodeId, status) {
        const node = this.nodes.get(nodeId);
        if (node) {
            node.status = status;
            const config = this.getDeviceNodeConfig(node);
            this.nodes.update(config);
        }
    }

    // -----------------------------------------------------------
    // 链路操作
    // -----------------------------------------------------------

    addConnection(from, to, options = {}) {
        const edgeId = `${from}-${to}`;
        const reverseId = `${to}-${from}`;

        // 检查是否已存在（正向或反向）
        if (this.edges.get(edgeId) || this.edges.get(reverseId)) {
            return;
        }

        const edgeConfig = {
            id: edgeId,
            from: from,
            to: to,
            color: {
                color: options.color || '#64748b',
                highlight: options.highlight || '#94a3b8',
                opacity: options.opacity || 1
            },
            width: options.width || 2,
            dashes: options.dashes || false,
            smooth: { type: 'continuous' },
            title: options.title || ''
        };

        this.edges.update(edgeConfig);
    }

    removeConnection(from, to) {
        const edgeId = `${from}-${to}`;
        this.edges.remove(edgeId);
    }

    updateConnectionStatus(from, to, status) {
        const edgeId = `${from}-${to}`;
        const edge = this.edges.get(edgeId);
        if (edge) {
            const color = status === 'up' ? '#10b981' : '#ef4444';
            this.edges.update({ id: edgeId, color: { color: color, highlight: color } });
        }
    }

    // -----------------------------------------------------------
    // 从 API 加载拓扑数据
    // -----------------------------------------------------------

    async loadTopologyData() {
        try {
            const response = await fetch('/api/v1/topology/data');
            const result = await response.json();

            if (result.code === 0 && result.data) {
                this.renderTopology(result.data);
            } else {
                console.log('没有拓扑数据，显示默认拓扑');
                this.renderDefaultTopology();
            }
        } catch (error) {
            console.error('加载拓扑数据失败:', error);
            this.renderDefaultTopology();
        }
    }

    renderTopology(data) {
        // 清空
        this.nodes.clear();
        this.edges.clear();

        // 添加节点
        if (data.nodes && data.nodes.length > 0) {
            data.nodes.forEach(node => this.addDeviceNode(node));
        }

        // 添加链路
        if (data.links && data.links.length > 0) {
            data.links.forEach(link => {
                const status = link.status || 'up';
                this.addConnection(link.source_node, link.target_node, {
                    color: status === 'up' ? '#10b981' : '#ef4444',
                    title: `${link.source_port || ''} <-> ${link.target_port || ''} [${status}]`
                });
            });
        }
    }

    renderDefaultTopology() {
        // 默认拓扑（没数据的时候显示）
        this.nodes.clear();
        this.edges.clear();

        const defaultDevices = [
            { id: 'cloud', name: '阿里云', type: 'cloud', status: 'online', ip: '-' },
            { id: 'core', name: '核心交换机', type: 'switch', vendor: 'H3C', status: 'online', ip: '192.168.1.1' },
            { id: 'sw1', name: 'SW1', type: 'switch', vendor: 'H3C', status: 'online', ip: '192.168.56.10' },
            { id: 'sw2', name: 'SW2', type: 'switch', vendor: 'Cisco', status: 'online', ip: '192.168.56.20' },
            { id: 'r1', name: 'R1', type: 'router', vendor: 'Huawei', status: 'online', ip: '192.168.56.30' },
        ];

        defaultDevices.forEach(d => this.addDeviceNode(d));

        this.addConnection('cloud', 'core', { color: '#3b82f6', dashes: true });
        this.addConnection('core', 'sw1', { color: '#10b981' });
        this.addConnection('core', 'sw2', { color: '#10b981' });
        this.addConnection('core', 'r1', { color: '#10b981' });
    }

    // -----------------------------------------------------------
    // 触发扫描
    // -----------------------------------------------------------

    async triggerScan(seedIp, community = 'public', scanMode = 'single', maxDepth = 3) {
        try {
            // 显示扫描中状态
            const modeNames = {'single': '单层', 'multi': '多层', 'mac_fallback': 'MAC回退'};
            if (typeof showToast === 'function') {
                showToast(`正在${modeNames[scanMode] || ''}扫描拓扑...`, 'info');
            }

            const response = await fetch('/api/v1/topology/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    seed_ip: seedIp,
                    community: community,
                    scan_mode: scanMode,
                    max_depth: maxDepth,
                    snmp_version: 'v2c'
                })
            });

            const result = await response.json();

            if (result.code === 0) {
                this.renderTopology(result.data);
                if (typeof showToast === 'function') {
                    showToast(`扫描完成！发现 ${result.data.metadata.device_count} 个设备，${result.data.metadata.link_count} 条链路`, 'success');
                }
                return result.data;
            } else {
                console.error('扫描失败:', result.msg);
                if (typeof showToast === 'function') {
                    showToast('扫描失败: ' + result.msg, 'error');
                }
                return null;
            }
        } catch (error) {
            console.error('扫描请求失败:', error);
            if (typeof showToast === 'function') {
                showToast('扫描请求失败: ' + error.message, 'error');
            }
            return null;
        }
    }

    // -----------------------------------------------------------
    // 保存快照
    // -----------------------------------------------------------

    async saveSnapshot(name) {
        try {
            const response = await fetch('/api/v1/topology/snapshot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });

            const result = await response.json();
            if (result.code === 0) {
                if (typeof showToast === 'function') {
                    showToast('快照保存成功', 'success');
                }
                return result.data;
            } else {
                console.error('保存快照失败:', result.msg);
                return null;
            }
        } catch (error) {
            console.error('保存快照请求失败:', error);
            return null;
        }
    }

    // -----------------------------------------------------------
    // 导出功能
    // -----------------------------------------------------------

    exportAsPNG(filename = 'topology') {
        if (!this.network) return;

        // vis.js 导出 canvas
        const canvas = this.container.querySelector('canvas');
        if (canvas) {
            const link = document.createElement('a');
            link.download = `${filename}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
        }
    }

    exportAsJSON(filename = 'topology') {
        const data = {
            nodes: this.nodes.get(),
            links: this.edges.get(),
            export_time: new Date().toISOString()
        };

        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const link = document.createElement('a');
        link.download = `${filename}.json`;
        link.href = URL.createObjectURL(blob);
        link.click();
    }

    exportAsCSV(filename = 'device_list') {
        // 导出设备清单为 CSV 格式，Excel 能直接打开
        const nodes = this.nodes.get();

        // CSV 表头
        const headers = ['设备ID', '设备名称', 'IP地址', '设备类型', '厂商', '网络层级', '状态'];

        // CSV 内容
        const rows = nodes.map(node => [
            node.node_id || '',
            node.name || '',
            node.ip_address || '',
            node.device_type || '',
            node.vendor || '',
            node.layer || '',
            node.status || '',
        ]);

        // 拼成 CSV 字符串（处理中文和特殊字符）
        const csvContent = [
            headers.join(','),
            ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
        ].join('\n');

        // 加 BOM 头，解决 Excel 打开中文乱码
        const bom = '﻿';
        const blob = new Blob([bom + csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.download = `${filename}.csv`;
        link.href = URL.createObjectURL(blob);
        link.click();
    }

    // -----------------------------------------------------------
    // 布局控制
    // -----------------------------------------------------------

    autoLayout() {
        if (this.network) this.network.stabilize();
    }

    fitAll() {
        if (this.network) this.network.fit({ animation: true });
    }

    focusNode(nodeId) {
        if (this.network) {
            this.network.focus(nodeId, {
                scale: 1.5,
                animation: { duration: 1000, easingFunction: 'easeInOutQuad' }
            });
        }
    }

    refresh() {
        this.loadTopologyData();
    }

    destroy() {
        if (this.network) {
            this.network.destroy();
            this.network = null;
        }
    }
}

// ============================================================
// 全局实例和快捷函数
// ============================================================

let topologyInstance = null;

function initTopology(containerId = 'topologyCanvas') {
    if (topologyInstance) {
        topologyInstance.destroy();
    }
    topologyInstance = new NetworkTopology(containerId);
    topologyInstance.loadTopologyData();
    return topologyInstance;
}

function refreshTopology() {
    if (topologyInstance) topologyInstance.refresh();
}

function autoLayoutTopology() {
    if (topologyInstance) topologyInstance.autoLayout();
}

function fitTopology() {
    if (topologyInstance) topologyInstance.fitAll();
}

function scanTopology(seedIp, community, scanMode = 'single', maxDepth = 3) {
    if (topologyInstance) return topologyInstance.triggerScan(seedIp, community, scanMode, maxDepth);
}

function saveTopologySnapshot(name) {
    if (topologyInstance) return topologyInstance.saveSnapshot(name);
}

function exportTopologyPNG(filename) {
    if (topologyInstance) topologyInstance.exportAsPNG(filename);
}

function exportTopologyJSON(filename) {
    if (topologyInstance) topologyInstance.exportAsJSON(filename);
}

function exportTopologyCSV(filename) {
    if (topologyInstance) topologyInstance.exportAsCSV(filename);
}

// 挂到 window 上
window.NetworkTopology = NetworkTopology;
window.initTopology = initTopology;
window.refreshTopology = refreshTopology;
window.autoLayoutTopology = autoLayoutTopology;
window.fitTopology = fitTopology;
window.scanTopology = scanTopology;
window.saveTopologySnapshot = saveTopologySnapshot;
window.exportTopologyPNG = exportTopologyPNG;
window.exportTopologyJSON = exportTopologyJSON;
