const MQTT_CFG = {
    url: 'wss://5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud:8884/mqtt',
    options: {
        username: 'lhuy04',
        password: 'Hcmute2026',
        protocol: 'wss',
        port: 8884,
        clean: true,
        connectTimeout: 4000
    }
};

function getClientId(prefix = 'web') {
    return `${prefix}_${Math.random().toString(16).substr(2, 8)}`;
}

function authGuard() {
    const token  = sessionStorage.getItem('_at');
    const expiry = parseInt(sessionStorage.getItem('_ae') || '0');
    if (!token || Date.now() > expiry) {
        sessionStorage.clear();
        localStorage.removeItem('isLoggedIn');
        location.href = 'login.html';
    }
}

function doLogout() {
    sessionStorage.clear();
    localStorage.removeItem('isLoggedIn');
    localStorage.removeItem('plcConnected');
    location.href = 'index.html';
}

const _escMap = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' };
function escapeHtml(str) {
    return String(str ?? '').replace(/[&<>"']/g, c => _escMap[c]);
}

function computeStats(data) {
    const hourImp = Array(12).fill(0), hourExp = Array(12).fill(0);
    const slotImp = Array(9).fill(0),  slotExp = Array(9).fill(0);
    let imports = 0, exports = 0;
    data.forEach(item => {
        const act  = (item.act || item.action || '').toUpperCase();
        const idx  = parseInt(String(item.time || item.timestamp || '0').split(':')[0]) - 6;
        const sNum = parseInt(String(item.slot || item.slot_id || '0').replace(/\D/g, '')) - 1;
        if (act === 'IMPORT') imports++;
        else if (act === 'EXPORT') exports++;
        if (idx >= 0 && idx < 12) { act === 'IMPORT' ? hourImp[idx]++ : act === 'EXPORT' ? hourExp[idx]++ : 0; }
        if (sNum >= 0 && sNum < 9) { act === 'IMPORT' ? slotImp[sNum]++ : act === 'EXPORT' ? slotExp[sNum]++ : 0; }
    });
    return { imports, exports, hourImp, hourExp, slotImp, slotExp };
}
