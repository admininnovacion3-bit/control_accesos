const view = document.body.dataset.view;
const toast = document.querySelector("#toast");
let currentUser = null;
let adminRows = [];
let pendingRegistration = null;

// Punto único para las llamadas al backend: conserva aquí el manejo de errores HTTP.
async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "No fue posible completar la operación");
  return data;
}
function notify(message) {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3200);
}
function closeModals() {
  // Cerrar por X descarta cualquier valor sensible o borrador del modal.
  document.querySelectorAll(".modal-backdrop").forEach((item) => item.classList.add("is-hidden"));
  document.querySelectorAll(".modal form").forEach((form) => form.reset());
  pendingRegistration = null;
}
function openModal(id) {
  document.querySelector("#" + id).classList.remove("is-hidden");
}
function make(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function addCell(row, text) {
  const cell = make("td", text == null ? "—" : text);
  row.append(cell);
  return cell;
}
function initials(name) {
  return name
    .split(" ")
    .map((word) => word[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
function goToDashboard() {
  window.location.href = currentUser.role === "admin" ? "/administrador" : "/empleado";
}

function setupModals() {
  // Los modales ya están definidos en cada HTML; JS solo cambia su visibilidad.
  document
    .querySelectorAll("[data-open-modal]")
    .forEach((button) => (button.onclick = () => openModal(button.dataset.openModal)));
  document
    .querySelectorAll("[data-close-modal]")
    .forEach((button) => (button.onclick = closeModals));
  document.querySelectorAll("[data-switch-modal]").forEach(
    (button) =>
      (button.onclick = () => {
        closeModals();
        openModal(button.dataset.switchModal);
      }),
  );
  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.onclick = () => {
      const input = button.parentElement.querySelector("input");
      const visible = input.type === "text";
      input.type = visible ? "password" : "text";
      button.setAttribute("aria-label", visible ? "Mostrar contraseña" : "Ocultar contraseña");
      button.textContent = visible ? "◉" : "◉̸";
    };
  });
  // Evita espacios, letras y símbolos antes de enviar; el backend vuelve a validarlo.
  document
    .querySelectorAll('input[name="first_name"], input[name="last_name"]')
    .forEach((input) => {
      input.oninput = () => (input.value = input.value.replace(/[^A-Za-zÁÉÍÓÚáéíóúÑñ]/g, ""));
    });
  document.querySelectorAll('input[name="document_number"]').forEach((input) => {
    input.oninput = () => (input.value = input.value.replace(/\D/g, "").slice(0, 15));
  });
  // Contraseñas de registro: elimina espacios incluso cuando se pegan desde el portapapeles.
  document
    .querySelectorAll(
      '#register-form input[name="password"], #register-form input[name="password_confirmation"]',
    )
    .forEach((input) => {
      input.addEventListener("input", () => {
        input.value = input.value.replace(/\s/g, "");
      });
    });
}
function fillUser() {
  const name = currentUser.first_name + " " + currentUser.last_name;
  document.querySelectorAll("[data-user-name]").forEach((element) => (element.textContent = name));
  document
    .querySelectorAll("[data-user-first-name]")
    .forEach((element) => (element.textContent = currentUser.first_name));
  document
    .querySelectorAll("[data-user-initials]")
    .forEach((element) => (element.textContent = initials(name)));
}
async function loadDocumentTypes() {
  const data = await api("/api/document-types");
  document.querySelectorAll("[data-document-types]").forEach((select) => {
    const selected = select.value;
    select.replaceChildren(make("option", "Selecciona una opción"));
    select.options[0].value = "";
    data.rows.forEach((type) => {
      const option = make("option", type.name);
      option.value = type.name;
      select.append(option);
    });
    select.value = selected;
  });
}

function setupPublic() {
  const password = document.querySelector('#register-form [name="password"]');
  const confirmation = document.querySelector('#register-form [name="password_confirmation"]');
  const validateRegistrationPasswords = () => {
    const validPassword = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?!.*\s).{10,}$/.test(password.value);
    password.setCustomValidity(
      password.value && !validPassword
        ? "La contraseña requiere 10 caracteres, mayúscula, minúscula, número y sin espacios"
        : "",
    );
    confirmation.setCustomValidity(
      confirmation.value && confirmation.value !== password.value
        ? "Las contraseñas no coinciden"
        : "",
    );
  };
  password.oninput = validateRegistrationPasswords;
  confirmation.oninput = validateRegistrationPasswords;

  document.querySelector("#login-form").onsubmit = async (event) => {
    event.preventDefault();
    try {
      currentUser = (
        await api("/api/login", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
        })
      ).user;
      goToDashboard();
    } catch (error) {
      notify(error.message);
    }
  };
  document.querySelector("#register-form").onsubmit = (event) => {
    event.preventDefault();
    const form = event.target;
    if (!form.checkValidity()) return form.reportValidity();
    const data = Object.fromEntries(new FormData(form));
    if (data.password !== data.password_confirmation) return notify("Las contraseñas no coinciden");
    if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?!.*\s).{10,}$/.test(data.password)) {
      return notify(
        "La contraseña requiere 10 caracteres, mayúscula, minúscula, número y sin espacios",
      );
    }
    pendingRegistration = data;
    document.querySelector("#register-modal").classList.add("is-hidden");
    openModal("super-admin-modal");
  };
  document.querySelector("#super-admin-form").onsubmit = async (event) => {
    event.preventDefault();
    try {
      if (!pendingRegistration) return;
      pendingRegistration.super_admin_password = new FormData(event.target).get(
        "super_admin_password",
      );
      currentUser = (
        await api("/api/register", {
          method: "POST",
          body: JSON.stringify(pendingRegistration),
        })
      ).user;
      goToDashboard();
    } catch (error) {
      notify(error.message);
    }
  };
  loadDocumentTypes().catch((error) => notify(error.message));
}
function renderEmployeeRows(rows) {
  const target = document.querySelector("#employee-rows");
  target.replaceChildren();
  rows.forEach((item) => {
    const row = document.createElement("tr");
    addCell(row, item.date);
    addCell(row, item.check_in);
    addCell(row, item.check_out);
    const cell = addCell(row, "");
    const state = make(
      "span",
      item.check_out ? "Completo" : "Pendiente",
      "status" + (item.check_out ? "" : " late"),
    );
    cell.append(state);
    target.append(row);
  });
}
async function loadEmployee() {
  // El backend decide el estado real del día; nunca se infiere solo desde el navegador.
  try {
    const data = await api("/api/employee/attendance");
    renderEmployeeRows(data.rows);
    const button = document.querySelector("#attendance-action");
    if (!data.today || !data.today.check_in) {
      button.textContent = "Marcar ingreso ↗";
      button.disabled = false;
      button.onclick = requestCode;
    } else if (!data.today.check_out) {
      button.textContent = "Marcar salida ↗";
      button.disabled = false;
      button.onclick = () => openModal("checkout-modal");
    } else {
      button.textContent = "Jornada completada";
      button.disabled = true;
    }
  } catch (error) {
    notify(error.message);
  }
}
async function requestCode() {
  try {
    const data = await api("/api/employee/request-code", { method: "POST" });
    notify(data.message);
    openModal("code-modal");
  } catch (error) {
    notify(error.message);
  }
}
function setupEmployee() {
  fillUser();
  document.querySelector("#current-date").textContent = new Date().toLocaleDateString("es-CO", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const clock = () =>
    (document.querySelector("#clock").textContent = new Date().toLocaleTimeString("es-CO", {
      hour: "2-digit",
      minute: "2-digit",
    }));
  clock();
  setInterval(clock, 1000);
  document.querySelector("#code-form").onsubmit = async (event) => {
    event.preventDefault();
    try {
      const data = await api("/api/employee/verify-code", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
      });
      closeModals();
      notify(data.message);
      loadEmployee();
    } catch (error) {
      notify(error.message);
    }
  };
  document.querySelector("#confirm-checkout").onclick = async () => {
    try {
      const data = await api("/api/employee/check-out", { method: "POST" });
      closeModals();
      notify(data.message);
      loadEmployee();
    } catch (error) {
      notify(error.message);
    }
  };
  document.querySelector("#edit-profile").onclick = async () => {
    try {
      await loadDocumentTypes();
      const data = await api("/api/employee/profile");
      const form = document.querySelector("#profile-form");
      Object.entries(data.profile).forEach(([key, value]) => {
        if (form.elements[key]) form.elements[key].value = value;
      });
      openModal("profile-modal");
    } catch (error) {
      notify(error.message);
    }
  };
  document.querySelector("#profile-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    if (!form.checkValidity()) return form.reportValidity();
    try {
      const data = await api("/api/employee/profile", {
        method: "PUT",
        body: JSON.stringify(Object.fromEntries(new FormData(form))),
      });
      currentUser = data.user;
      fillUser();
      closeModals();
      notify(data.message);
    } catch (error) {
      notify(error.message);
    }
  };
  document.querySelector("#change-my-password").onclick = () =>
    openModal("employee-password-modal");
  document.querySelector("#employee-password-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    const data = Object.fromEntries(new FormData(form));
    if (data.password !== data.password_confirmation) return notify("Las contraseñas no coinciden");
    try {
      const result = await api("/api/employee/change-password", {
        method: "POST",
        body: JSON.stringify(data),
      });
      closeModals();
      notify(result.message);
    } catch (error) {
      notify(error.message);
    }
  };
  loadEmployee();
}
function renderMetrics(stats) {
  const target = document.querySelector("#metrics");
  target.replaceChildren();
  [
    ["Asistencias", stats.present, ""],
    ["Retardos", stats.late, ""],
    ["Horas laboradas", stats.hours, " h"],
    ["Empleados activos", stats.employees, ""],
  ].forEach((item) => {
    const card = make("article", undefined, "metric");
    card.append(
      make("div", item[0], "metric-label"),
      make("div", String(item[1]) + item[2], "metric-value"),
      make("div", "Datos del período seleccionado", "metric-note"),
    );
    target.append(card);
  });
}
function renderChart(points) {
  const target = document.querySelector("#chart");
  target.replaceChildren();
  points.forEach((point) => {
    const bar = make("div", undefined, "bar");
    bar.style.height = point.percent + "%";
    bar.dataset.value = point.value;
    bar.append(make("span", point.day, "bar-label"));
    target.append(bar);
  });
}
function renderInsights(stats) {
  const target = document.querySelector("#admin-insights");
  target.replaceChildren();
  [
    ["A tiempo", Math.max(0, stats.present - stats.late) + " registros"],
    ["Retardos", stats.late + " registros"],
    ["Horas acumuladas", stats.hours + " h"],
  ].forEach((item) => {
    const row = make("div", undefined, "person");
    row.append(
      make("div", item[0][0], "avatar"),
      make("div", item[0], "person-info"),
      make("b", item[1]),
    );
    target.append(row);
  });
}
function visibleRows() {
  return adminRows.filter((row) =>
    row.name.toLowerCase().includes(document.querySelector("#search").value.toLowerCase()),
  );
}
function renderAdminRows() {
  const target = document.querySelector("#admin-rows");
  target.replaceChildren();
  visibleRows().forEach((item) => {
    const row = document.createElement("tr"),
      selector = document.createElement("input");
    selector.type = "checkbox";
    selector.className = "row-select";
    selector.dataset.key = item.employee_id + item.date;
    const selectCell = addCell(row, "");
    selectCell.append(selector);
    addCell(row, item.name);
    addCell(row, item.date);
    addCell(row, item.check_in);
    addCell(row, item.check_out);
    const stateCell = addCell(row, "");
    stateCell.append(
      make("span", item.status, "status" + (item.status === "Retardo" ? " late" : "")),
    );
    addCell(row, item.hours);
    target.append(row);
  });
}
async function loadAdmin() {
  // Los filtros de fecha se envían al servidor antes de actualizar gráficas y tabla.
  try {
    const params = new URLSearchParams(),
      start = document.querySelector("#start-date").value,
      end = document.querySelector("#end-date").value;
    if (start) params.set("start", start);
    if (end) params.set("end", end);
    const data = await api("/api/admin/summary?" + params);
    adminRows = data.rows;
    renderMetrics(data.stats);
    renderChart(data.chart);
    renderInsights(data.stats);
    renderAdminRows();
  } catch (error) {
    notify(error.message);
  }
}
function selectedRows() {
  const keys = [...document.querySelectorAll(".row-select:checked")].map(
    (input) => input.dataset.key,
  );
  return keys.length
    ? adminRows.filter((row) => keys.includes(row.employee_id + row.date))
    : visibleRows();
}
function exportExcel() {
  // Si hay checkboxes seleccionados se exportan solo esas filas; si no, lo visible.
  const rows = selectedRows(),
    csv = [
      ["Empleado", "Fecha", "Ingreso", "Salida", "Estado", "Horas"],
      ...rows.map((r) => [r.name, r.date, r.check_in, r.check_out, r.status, r.hours]),
    ]
      .map((line) =>
        line.map((v) => '"' + String(v == null ? "" : v).replaceAll('"', '""') + '"').join(","),
      )
      .join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
  link.download = "asistencias.csv";
  link.click();
  notify("Excel exportado");
}
function setupAdmin() {
  fillUser();
  document.querySelector("#search").oninput = renderAdminRows;
  document
    .querySelectorAll("#start-date, #end-date")
    .forEach((input) => (input.onchange = loadAdmin));
  document.querySelector("#select-all").onchange = (event) =>
    document
      .querySelectorAll(".row-select")
      .forEach((input) => (input.checked = event.target.checked));
  document.querySelector("#export-excel").onclick = exportExcel;
  document.querySelector("#export-pdf").onclick = () => window.print();
  document.querySelector("#change-password").onclick = async () => {
    openModal("password-modal");
  };
  document.querySelector("#password-form").onsubmit = async (event) => {
    event.preventDefault();
    try {
      const data = await api("/api/admin/change-password", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
      });
      closeModals();
      notify(data.message);
      event.target.reset();
    } catch (error) {
      notify(error.message);
    }
  };
  document.querySelector('#password-form [name="document_number"]').oninput = (event) => {
    event.target.value = event.target.value.replace(/\D/g, "").slice(0, 15);
  };
  loadAdmin();
}
async function boot() {
  // La vista HTML y el rol de sesión deben coincidir antes de activar sus interacciones.
  setupModals();
  if (view === "public") return setupPublic();
  try {
    currentUser = (await api("/api/session")).user;
    if (!currentUser) return window.location.assign("/");
    if (currentUser.role !== view) return goToDashboard();
    document.querySelector("#logout").onclick = async () => {
      await api("/api/logout", { method: "POST" });
      window.location.href = "/";
    };
    view === "admin" ? setupAdmin() : setupEmployee();
  } catch {
    window.location.href = "/";
  }
}
boot();
