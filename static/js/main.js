document.addEventListener('DOMContentLoaded', () => {
    // 1. Asynchronous Dropdown State Selectors
    document.querySelectorAll('.card-status-select').forEach(el => {
        el.addEventListener('change', async (e) => {
            const jobId = e.target.dataset.jobId;
            await postUpdate('/api/update-job', { job_id: jobId, status: e.target.value });
        });
    });

    document.querySelectorAll('.admin-role-select').forEach(el => {
        el.addEventListener('change', async (e) => {
            const uid = e.target.dataset.userId;
            await postUpdate('/admin/user/change-role', { user_id: uid, role: e.target.value });
        });
    });

    // 2. Control console profile modifiers
    document.querySelectorAll('.btn-admin-action').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const uid = e.target.dataset.userId;
            const actionType = e.target.dataset.action;
            if (actionType === 'delete' && !confirm('Permanently remove profile index record?')) return;
            await postUpdate('/admin/user/action', { user_id: uid, action: actionType });
        });
    });
});

async function postUpdate(url, payload) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (data.success) { window.location.reload(); }
        else { alert('Transaction declined: ' + (data.error || 'Unknown execution trace')); }
    } catch (err) {
        alert('Pipeline transmission loss.');
    }
}
