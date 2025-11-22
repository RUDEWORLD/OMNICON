// Omnicon Web GUI JavaScript

// Global variables
let currentSystemInfo = {};
let currentNetworkSettings = {};
let updateCheckInterval = null;

// Show toast notification
function showToast(title, message, type = 'info') {
    const toast = document.getElementById('liveToast');
    const toastTitle = document.getElementById('toastTitle');
    const toastBody = document.getElementById('toastBody');

    toastTitle.textContent = title;
    toastBody.textContent = message;

    // Set color based on type
    const toastHeader = toast.querySelector('.toast-header');
    toastHeader.className = 'toast-header';

    switch(type) {
        case 'success':
            toastHeader.style.backgroundColor = '#28a745';
            break;
        case 'error':
            toastHeader.style.backgroundColor = '#dc3545';
            break;
        case 'warning':
            toastHeader.style.backgroundColor = '#ffc107';
            toastHeader.style.color = '#000';
            break;
        default:
            toastHeader.style.backgroundColor = '#17a2b8';
    }

    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
}

// Load system information
function loadSystemInfo() {
    $.ajax({
        url: '/api/system/info',
        method: 'GET',
        success: function(data) {
            currentSystemInfo = data;
            updateSystemInfoDisplay(data);
        },
        error: function(xhr) {
            console.error('Failed to load system info:', xhr);
            showToast('Error', 'Failed to load system information', 'error');
        }
    });
}

// Update system info display
function updateSystemInfoDisplay(data) {
    let html = '<div class="system-info">';

    // Service status
    if (data.active_service === 'companion') {
        $('#companionBtn').addClass('active');
        $('#satelliteBtn').removeClass('active');
        $('#companionStatus').html('<small class="badge bg-success">Active</small>');
        $('#satelliteStatus').html('<small class="badge bg-secondary">Inactive</small>');
    } else if (data.active_service === 'satellite') {
        $('#satelliteBtn').addClass('active');
        $('#companionBtn').removeClass('active');
        $('#satelliteStatus').html('<small class="badge bg-success">Active</small>');
        $('#companionStatus').html('<small class="badge bg-secondary">Inactive</small>');
    } else {
        $('#companionBtn, #satelliteBtn').removeClass('active');
        $('#companionStatus, #satelliteStatus').html('<small class="badge bg-secondary">Inactive</small>');
    }

    // System stats
    html += `
        <div class="system-info-item">
            <span class="system-info-label">IP Address:</span>
            <span class="system-info-value">${data.ip_address || 'N/A'}</span>
        </div>
        <div class="system-info-item">
            <span class="system-info-label">Service Port:</span>
            <span class="system-info-value">${data.service_port || 'N/A'}</span>
        </div>
        <div class="system-info-item">
            <span class="system-info-label">Temperature:</span>
            <span class="system-info-value">${data.temperature || 'N/A'}</span>
        </div>
        <div class="system-info-item">
            <span class="system-info-label">CPU Usage:</span>
            <span class="system-info-value">${data.cpu_usage}%</span>
            <div class="progress mt-1">
                <div class="progress-bar bg-primary" style="width: ${data.cpu_usage}%"></div>
            </div>
        </div>
    `;

    if (data.memory) {
        html += `
            <div class="system-info-item">
                <span class="system-info-label">Memory:</span>
                <span class="system-info-value">${data.memory.used}GB / ${data.memory.total}GB (${data.memory.percent}%)</span>
                <div class="progress mt-1">
                    <div class="progress-bar bg-info" style="width: ${data.memory.percent}%"></div>
                </div>
            </div>
        `;
    }

    if (data.disk) {
        html += `
            <div class="system-info-item">
                <span class="system-info-label">Disk:</span>
                <span class="system-info-value">${data.disk.used}GB / ${data.disk.total}GB (${data.disk.percent}%)</span>
                <div class="progress mt-1">
                    <div class="progress-bar bg-warning" style="width: ${data.disk.percent}%"></div>
                </div>
            </div>
        `;
    }

    html += '</div>';
    $('#systemInfo').html(html);
}

// Load network settings
function loadNetworkSettings() {
    $.ajax({
        url: '/api/network/settings',
        method: 'GET',
        success: function(data) {
            currentNetworkSettings = data;
            updateNetworkDisplay(data);
        },
        error: function(xhr) {
            console.error('Failed to load network settings:', xhr);
            showToast('Error', 'Failed to load network settings', 'error');
        }
    });
}

// Update network display
function updateNetworkDisplay(data) {
    // In DHCP mode, show actual network configuration
    // In STATIC mode, show configured static values
    const subnet = data.network_mode === 'DHCP' ? (data.actual_subnet || 'N/A') : (data.actual_subnet || data.static_subnet || 'N/A');
    const gateway = data.network_mode === 'DHCP' ? (data.actual_gateway || 'N/A') : (data.actual_gateway || data.static_gateway || 'N/A');
    const dns = data.actual_dns || 'N/A';

    let html = `
        <table class="network-info-table">
            <tr>
                <td>Current IP:</td>
                <td><strong>${data.current_ip || 'N/A'}</strong></td>
            </tr>
            <tr>
                <td>Subnet Mask:</td>
                <td>${subnet}</td>
            </tr>
            <tr>
                <td>Gateway:</td>
                <td>${gateway}</td>
            </tr>
            <tr>
                <td>DNS Servers:</td>
                <td>${dns}</td>
            </tr>
            <tr>
                <td>Mode:</td>
                <td><span class="badge bg-${data.network_mode === 'DHCP' ? 'primary' : 'success'}">${data.network_mode || 'N/A'}</span></td>
            </tr>
        </table>
    `;

    $('#networkInfo').html(html);

    // Update network mode buttons
    if (data.network_mode === 'DHCP' || data.active_profile === 'DHCP') {
        $('#dhcpMode').prop('checked', true);
        $('#staticMode').prop('checked', false);
    } else {
        $('#staticMode').prop('checked', true);
        $('#dhcpMode').prop('checked', false);
    }

    // Update static config fields
    $('#staticIp').val(data.static_ip || '');
    $('#staticSubnet').val(data.static_subnet || '');
    $('#staticGateway').val(data.static_gateway || '');
}

// Toggle service
function toggleService(service) {
    const btn = service === 'companion' ? $('#companionBtn') : $('#satelliteBtn');
    btn.addClass('updating');

    $.ajax({
        url: '/api/service/toggle',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({service: service}),
        success: function(data) {
            showToast('Success', `Switched to ${service} service`, 'success');
            setTimeout(loadSystemInfo, 2000);
        },
        error: function(xhr) {
            console.error('Failed to toggle service:', xhr);
            showToast('Error', 'Failed to toggle service', 'error');
        },
        complete: function() {
            btn.removeClass('updating');
        }
    });
}

// Set network mode
function setNetworkMode(mode) {
    $.ajax({
        url: '/api/network/mode',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({mode: mode}),
        success: function(data) {
            showToast('Success', `Switched to ${mode} mode`, 'success');
            setTimeout(loadNetworkSettings, 2000);
        },
        error: function(xhr) {
            console.error('Failed to set network mode:', xhr);
            showToast('Error', 'Failed to set network mode', 'error');
        }
    });
}

// Show static configuration modal
function showStaticConfig() {
    const modal = new bootstrap.Modal(document.getElementById('staticConfigModal'));
    modal.show();
}

// Save static configuration
function saveStaticConfig() {
    const ip = $('#staticIp').val();
    const subnet = $('#staticSubnet').val();
    const gateway = $('#staticGateway').val();

    // Basic validation
    const ipRegex = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/;
    if (!ipRegex.test(ip) || !ipRegex.test(subnet) || !ipRegex.test(gateway)) {
        showToast('Error', 'Invalid IP address format', 'error');
        return;
    }

    $.ajax({
        url: '/api/network/static',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            ip: ip,
            subnet: subnet,
            gateway: gateway
        }),
        success: function(data) {
            showToast('Success', 'Static IP configuration saved', 'success');
            bootstrap.Modal.getInstance(document.getElementById('staticConfigModal')).hide();
            setTimeout(loadNetworkSettings, 2000);
        },
        error: function(xhr) {
            console.error('Failed to save static config:', xhr);
            showToast('Error', 'Failed to save static configuration', 'error');
        }
    });
}

// Load version information
function loadVersionInfo() {
    $.ajax({
        url: '/api/update/check',
        method: 'GET',
        success: function(data) {
            updateVersionDisplay(data);
        },
        error: function(xhr) {
            console.error('Failed to load version info:', xhr);
        }
    });
}

// Update version display
function updateVersionDisplay(data) {
    let html = '<div class="version-info">';

    if (data.current_versions) {
        html += `
            <div class="mb-2">
                <strong>Omnicon:</strong> ${data.current_versions.omnicon || 'Unknown'}
                ${data.omnicon_update_available ? ' <span class="badge bg-warning">Update Available</span>' : ''}
            </div>
            <div class="mb-2">
                <strong>Companion:</strong> ${data.current_versions.companion || 'N/A'}
            </div>
            <div class="mb-2">
                <strong>Satellite:</strong> ${data.current_versions.satellite || 'N/A'}
            </div>
        `;
    }

    html += '</div>';
    $('#versionInfo').html(html);
}

// Check for updates
function checkUpdates() {
    loadVersionInfo();
    showToast('Info', 'Checking for updates...', 'info');
}

// Update Companion
function updateCompanion() {
    if (!confirm('Update Companion to the latest stable version? The system will reboot after update.')) {
        return;
    }

    $.ajax({
        url: '/api/update/companion',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({beta: false}),
        success: function(data) {
            showToast('Success', 'Companion update started. System will reboot.', 'success');
        },
        error: function(xhr) {
            const response = xhr.responseJSON;
            showToast('Error', response.error || 'Failed to update Companion', 'error');
        }
    });
}

// Update Satellite
function updateSatellite() {
    if (!confirm('Update Satellite to the latest stable version? The system will reboot after update.')) {
        return;
    }

    $.ajax({
        url: '/api/update/satellite',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({beta: false}),
        success: function(data) {
            showToast('Success', 'Satellite update started. System will reboot.', 'success');
        },
        error: function(xhr) {
            const response = xhr.responseJSON;
            showToast('Error', response.error || 'Failed to update Satellite', 'error');
        }
    });
}

// Check Omnicon version (for display)
function checkOmniconVersion() {
    $.ajax({
        url: '/api/omnicon/check_update',
        method: 'GET',
        success: function(data) {
            $('#currentOmniconVersion').text(data.current_version || '--');
            $('#availableOmniconVersion').text(data.latest_version || '--');

            // Store data globally for modal use
            window.omniconUpdateData = data;
        },
        error: function(xhr) {
            console.error('Failed to check Omnicon version:', xhr);
            $('#currentOmniconVersion').text('Error');
            $('#availableOmniconVersion').text('Error');
        }
    });
}

// Show Omnicon update modal
function showOmniconUpdate() {
    const modal = new bootstrap.Modal(document.getElementById('omniconUpdateModal'));
    modal.show();

    // Reset modal state
    $('#updateCheckStatus').show();
    $('#updateVersionInfo').hide();
    $('#updateButton').hide();

    // Check for updates
    $.ajax({
        url: '/api/omnicon/check_update',
        method: 'GET',
        success: function(data) {
            $('#updateCheckStatus').hide();
            $('#updateVersionInfo').show();

            $('#modalCurrentVersion').text(data.current_version || 'Unknown');
            $('#modalLatestVersion').text(data.latest_version || 'Unknown');

            // Store latest version for update
            window.selectedOmniconVersion = data.latest_version;

            if (data.update_available) {
                $('#updateMessage').html('<div class="alert alert-success">An update is available!</div>');
                $('#updateButton').show();
            } else if (data.current_version === 'Unknown' || data.latest_version === 'Check Failed') {
                $('#updateMessage').html('<div class="alert alert-warning">Unable to check for updates. Please check your internet connection.</div>');
            } else {
                $('#updateMessage').html('<div class="alert alert-info">You are running the latest version.</div>');
            }

            // Show available versions list
            if (data.available_versions && data.available_versions.length > 0) {
                let html = '<h6 class="mt-3">Available Versions:</h6>';
                html += '<div class="list-group" style="max-height: 200px; overflow-y: auto;">';
                data.available_versions.forEach(function(version) {
                    const isCurrent = version === data.current_version;
                    const badge = isCurrent ? ' <span class="badge bg-success">Current</span>' : '';
                    html += `
                        <a href="#" class="list-group-item list-group-item-action ${isCurrent ? 'active' : ''}"
                           onclick="selectOmniconVersion('${version}'); return false;">
                            <div class="d-flex w-100 justify-content-between">
                                <small>${version}${badge}</small>
                            </div>
                        </a>
                    `;
                });
                html += '</div>';
                $('#updateVersionList').html(html);
            }
        },
        error: function(xhr) {
            $('#updateCheckStatus').hide();
            $('#updateVersionInfo').show();
            $('#updateMessage').html('<div class="alert alert-danger">Failed to check for updates. Please try again later.</div>');
        }
    });
}

// Select a specific version to update to
function selectOmniconVersion(version) {
    window.selectedOmniconVersion = version;
    $('#updateButton').show().html(`<i class="fas fa-download"></i> Update to ${version}`);
}

// Perform Omnicon update
function performOmniconUpdate() {
    const version = window.selectedOmniconVersion;
    if (!version) {
        showToast('Error', 'No version selected', 'error');
        return;
    }

    if (!confirm(`Update Omnicon to version ${version}? The system will restart.`)) {
        return;
    }

    // Disable button and show loading state
    $('#updateButton').prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Updating...');

    $.ajax({
        url: '/api/omnicon/update',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({version: version}),
        success: function(data) {
            showToast('Success', `Updating to ${version}. The system will restart.`, 'success');
            bootstrap.Modal.getInstance(document.getElementById('omniconUpdateModal')).hide();

            // Show a permanent notification that the system is restarting
            setTimeout(function() {
                alert('Omnicon is updating and will restart. The page will reload in 10 seconds.');
                setTimeout(function() {
                    location.reload();
                }, 10000);
            }, 1000);
        },
        error: function(xhr) {
            const response = xhr.responseJSON;
            showToast('Error', response.error || 'Failed to update Omnicon', 'error');
            $('#updateButton').prop('disabled', false).html(`<i class="fas fa-download"></i> Update to ${version}`);
        }
    });
}

// Load date/time
function loadDateTime() {
    $.ajax({
        url: '/api/datetime',
        method: 'GET',
        cache: false,  // Force refresh from server
        timeout: 800,  // Short timeout since we're calling every second
        success: function(data) {
            const date = new Date(data.datetime);
            $('#currentDate').text(date.toLocaleDateString());
            $('#currentTime').text(date.toLocaleTimeString());

            // Only update timezone if it changed (less DOM updates)
            const currentTz = $('#currentTimezone').text();
            if (currentTz !== (data.timezone || 'UTC')) {
                $('#currentTimezone').text(data.timezone || 'UTC');
            }

            $('#format24hr').prop('checked', data.format_24hr);

            // Store timezone data for modal
            window.timezoneData = data;
        },
        error: function(xhr) {
            // Don't spam console with errors for frequent requests
            if (xhr.status !== 0) {  // 0 means request was aborted
                console.error('Failed to load date/time:', xhr);
            }
        }
    });
}

// Show date/time configuration modal
function showDateTimeConfig() {
    const now = new Date();
    $('#setDate').val(now.toISOString().split('T')[0]);
    $('#setTime').val(now.toTimeString().split(' ')[0]);

    const modal = new bootstrap.Modal(document.getElementById('dateTimeModal'));
    modal.show();
}

// Save date/time settings
function saveDateTime() {
    const date = $('#setDate').val();
    const time = $('#setTime').val();
    const format24hr = $('#format24hr').prop('checked');

    $.ajax({
        url: '/api/datetime',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            date: date,
            time: time,
            format_24hr: format24hr
        }),
        success: function(data) {
            showToast('Success', 'Date/time settings saved', 'success');
            bootstrap.Modal.getInstance(document.getElementById('dateTimeModal')).hide();
            loadDateTime();
        },
        error: function(xhr) {
            const response = xhr.responseJSON;
            showToast('Error', response.error || 'Failed to save date/time', 'error');
        }
    });
}

// Confirm power action
function confirmPowerAction(action) {
    const title = action === 'reboot' ? 'Confirm Reboot' : 'Confirm Shutdown';
    const message = action === 'reboot' ?
        'Are you sure you want to reboot the system?' :
        'Are you sure you want to shutdown the system?';

    $('#confirmTitle').text(title);
    $('#confirmBody').text(message);

    $('#confirmButton').off('click').on('click', function() {
        performPowerAction(action);
    });

    const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
    modal.show();
}

// Perform power action
function performPowerAction(action) {
    $.ajax({
        url: '/api/system/power',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({action: action}),
        success: function(data) {
            bootstrap.Modal.getInstance(document.getElementById('confirmModal')).hide();
            showToast('Warning', data.message, 'warning');
        },
        error: function(xhr) {
            const response = xhr.responseJSON;
            showToast('Error', response.error || 'Failed to perform power action', 'error');
        }
    });
}

// Show settings modal
function showSettings() {
    $.ajax({
        url: '/api/settings',
        method: 'GET',
        success: function(data) {
            $('#username').val(data.username);
            $('#auto_refresh').prop('checked', data.auto_refresh);
            $('#refresh_interval').val(data.refresh_interval);

            const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
            modal.show();
        },
        error: function(xhr) {
            showToast('Error', 'Failed to load settings', 'error');
        }
    });
}

// Save settings
function saveSettings() {
    const settings = {
        username: $('#username').val(),
        password: $('#password').val(),
        auto_refresh: $('#auto_refresh').prop('checked'),
        refresh_interval: parseInt($('#refresh_interval').val())
    };

    $.ajax({
        url: '/api/settings',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(settings),
        success: function(data) {
            showToast('Success', 'Settings saved successfully', 'success');
            bootstrap.Modal.getInstance(document.getElementById('settingsModal')).hide();

            // Clear password field
            $('#password').val('');

            // Update auto-refresh if changed
            if (settings.auto_refresh !== autoRefreshEnabled) {
                location.reload();
            }
        },
        error: function(xhr) {
            const response = xhr.responseJSON;
            showToast('Error', response.error || 'Failed to save settings', 'error');
        }
    });
}

// Show timezone configuration modal
function showTimezoneConfig() {
    if (!window.timezoneData || !window.timezoneData.available_timezones) {
        // Load timezone data first
        $.ajax({
            url: '/api/datetime',
            method: 'GET',
            success: function(data) {
                window.timezoneData = data;
                showTimezoneModal();
            },
            error: function() {
                showToast('Error', 'Failed to load timezone data', 'error');
            }
        });
    } else {
        showTimezoneModal();
    }
}

// Actually show the timezone modal
function showTimezoneModal() {
    const timezones = window.timezoneData.available_timezones || [];
    const currentTz = window.timezoneData.timezone || 'UTC';

    // Populate timezone select
    const select = $('#timezoneSelect');
    select.empty();

    timezones.forEach(tz => {
        const option = $('<option></option>').val(tz).text(tz);
        if (tz === currentTz) {
            option.prop('selected', true);
        }
        select.append(option);
    });

    $('#modalCurrentTz').text(currentTz);

    // Set up search functionality
    $('#timezoneSearch').off('input').on('input', function() {
        const searchTerm = $(this).val().toLowerCase();
        $('#timezoneSelect option').each(function() {
            const tzName = $(this).text().toLowerCase();
            if (tzName.includes(searchTerm)) {
                $(this).show();
            } else {
                $(this).hide();
            }
        });
    });

    const modal = new bootstrap.Modal(document.getElementById('timezoneModal'));
    modal.show();
}

// Debug timezone detection
function debugTimezone() {
    $.ajax({
        url: '/api/timezone/debug',
        method: 'GET',
        cache: false,
        success: function(data) {
            console.log('Timezone Debug Info:', data);

            // Create a formatted output
            let debugText = 'Timezone Debug Information:\n\n';

            if (data.timedatectl_status) {
                debugText += 'timedatectl status output:\n';
                debugText += data.timedatectl_status.stdout || 'No output';
                debugText += '\n\n';
            }

            if (data.timedatectl_show) {
                debugText += 'timedatectl show Timezone:\n';
                debugText += data.timedatectl_show.stdout || 'No output';
                debugText += '\n\n';
            }

            if (data.etc_timezone) {
                debugText += '/etc/timezone:\n';
                debugText += typeof data.etc_timezone === 'string' ? data.etc_timezone : JSON.stringify(data.etc_timezone);
                debugText += '\n\n';
            }

            if (data.etc_localtime) {
                debugText += '/etc/localtime:\n';
                debugText += JSON.stringify(data.etc_localtime, null, 2);
                debugText += '\n\n';
            }

            debugText += 'Running as user: ' + data.current_user;

            // Show in alert or console
            alert(debugText);

            // Also show in toast
            showToast('Debug', 'Check browser console for details', 'info');
        },
        error: function(xhr) {
            console.error('Debug failed:', xhr);
            showToast('Error', 'Failed to get debug info', 'error');
        }
    });
}

// Save timezone
function saveTimezone() {
    const selectedTz = $('#timezoneSelect').val();

    if (!selectedTz) {
        showToast('Error', 'Please select a timezone', 'error');
        return;
    }

    $.ajax({
        url: '/api/timezone',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            timezone: selectedTz
        }),
        success: function(data) {
            showToast('Success', `Timezone changed to ${selectedTz}`, 'success');
            bootstrap.Modal.getInstance(document.getElementById('timezoneModal')).hide();

            // Reload date/time to show new timezone
            setTimeout(loadDateTime, 1000);
        },
        error: function(xhr) {
            console.error('Failed to set timezone:', xhr);
            showToast('Error', 'Failed to set timezone', 'error');
        }
    });
}