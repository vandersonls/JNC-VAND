const state = {
  usuario: null,
  materiais: [],
  clientes: [],
  projetos: [],
  areas: [],
  projetoAtual: null,
};

async function garantirAreasCarregadas() {
  if (!state.areas.length) state.areas = await api("/api/areas");
  return state.areas;
}

// ---------- HELPERS ----------
async function api(url, options = {}) {
  const opts = { credentials: "include", headers: {}, ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(url, opts);
  if (resp.status === 401 && state.usuario) {
    // A sessão expirou (inatividade) enquanto a pessoa estava usando o
    // sistema - avisa e volta para a tela de login, sem pop-up de "sair?".
    state.usuario = null;
    toast("Sua sessão expirou por inatividade. Faça login novamente.", "erro");
    setTimeout(() => location.reload(), 1800);
    throw new Error("Sessão expirada");
  }
  let data = null;
  try { data = await resp.json(); } catch (_) { /* respostas binárias (excel/pdf) não chegam aqui */ }
  if (!resp.ok) {
    throw new Error((data && data.erro) || `Erro ${resp.status}`);
  }
  return data;
}

function toast(msg, tipo = "sucesso") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `toast ${tipo}`;
  el.classList.remove("oculto");
  setTimeout(() => el.classList.add("oculto"), 3000);
}

// Substitui o confirm() nativo do navegador (que mostra o domínio do
// Railway no título, ex.: "web-production-xxxx.up.railway.app diz") por
// uma caixa de diálogo própria, com a cara do sistema.
function confirmarPersonalizado(mensagem) {
  return new Promise((resolve) => {
    const overlay = document.getElementById("confirm-overlay");
    document.getElementById("confirm-mensagem").textContent = mensagem;
    overlay.classList.remove("oculto");
    const btnOk = document.getElementById("confirm-ok");
    const btnCancelar = document.getElementById("confirm-cancelar");
    const finalizar = (resultado) => {
      overlay.classList.add("oculto");
      btnOk.removeEventListener("click", onOk);
      btnCancelar.removeEventListener("click", onCancelar);
      resolve(resultado);
    };
    const onOk = () => finalizar(true);
    const onCancelar = () => finalizar(false);
    btnOk.addEventListener("click", onOk);
    btnCancelar.addEventListener("click", onCancelar);
  });
}

// Como o app é uma SPA, uma aba deixada aberta continua rodando o JS que
// tinha quando foi carregada, mesmo depois de um novo deploy no servidor.
// Isso checa periodicamente se a versão do app.js publicada mudou e, se
// mudou, mostra um aviso fixo pedindo pra recarregar - em vez da pessoa
// achar que uma correção "não funcionou" quando na verdade ela só está
// vendo o código antigo.
async function verificarNovaVersao() {
  try {
    const r = await fetch("/api/versao", { credentials: "include" });
    const dados = await r.json();
    if (dados.js && window.__VERSAO_JS_ATUAL__ && dados.js !== window.__VERSAO_JS_ATUAL__) {
      document.getElementById("aviso-nova-versao").classList.remove("oculto");
    }
  } catch (_) { /* falha de rede na checagem não deve incomodar ninguém */ }
}
document.getElementById("btn-recarregar-versao").addEventListener("click", () => location.reload());
setInterval(verificarNovaVersao, 5 * 60 * 1000);

function ehAdmin() {
  return state.usuario && (state.usuario.perfil === "master" || state.usuario.perfil === "administrador");
}

function ehMaster() {
  return state.usuario && state.usuario.perfil === "master";
}

function aplicarPermissoes() {
  document.querySelectorAll(".somente-admin").forEach((el) => {
    el.style.display = ehAdmin() ? "" : "none";
  });
  document.querySelectorAll(".somente-master").forEach((el) => {
    el.style.display = ehMaster() ? "" : "none";
  });
}

function abrirModal(html, extraClass = "") {
  const modal = document.getElementById("modal-conteudo");
  modal.className = `modal ${extraClass}`.trim();
  modal.classList.remove("modal-maximizado");
  document.getElementById("modal-corpo").innerHTML = html;
  document.getElementById("modal-overlay").classList.remove("oculto");
}
function fecharModal() {
  document.getElementById("modal-overlay").classList.add("oculto");
}
// Sempre pede confirmação antes de fechar, sem depender de detectar se algo
// mudou (evita qualquer chance de perder dados por falha em algum caso não
// coberto pelo rastreio de alterações). Clicar fora do modal não fecha mais
// nada - só os botões Cancelar/Fechar e Esc passam por aqui.
async function fecharModalComConfirmacao() {
  if (!(await confirmarPersonalizado("Deseja fechar esta janela? Alterações não salvas serão perdidas."))) {
    return;
  }
  fecharModal();
}
// Esc segue o mesmo aviso - é uma tecla de intenção clara, mas ainda assim
// não deve descartar um formulário em andamento sem confirmar.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("modal-overlay").classList.contains("oculto")) {
    fecharModalComConfirmacao();
  }
});

// Evita perda de trabalho: se o usuário tentar recarregar ou fechar a aba
// com algum pop-up aberto (edição em andamento), o navegador pergunta antes.
window.addEventListener("beforeunload", (e) => {
  const modalAberto = !document.getElementById("modal-overlay").classList.contains("oculto");
  if (modalAberto) {
    e.preventDefault();
    e.returnValue = "";
  }
});
document.getElementById("btn-modal-maximizar").addEventListener("click", () => {
  document.getElementById("modal-conteudo").classList.toggle("modal-maximizado");
});

// ---------- LOGIN ----------
async function verificarSessao() {
  const data = await api("/api/me");
  if (data.usuario) {
    state.usuario = data.usuario;
    mostrarApp();
  } else {
    document.getElementById("tela-login").classList.remove("oculto");
    document.getElementById("app").classList.add("oculto");
  }
}

// Gera o HTML de um campo de senha com botão de mostrar/ocultar (olho).
// Reutilizável em qualquer formulário/modal que precise de campo de senha.
function campoSenhaHtml(id, extraAttrs = "") {
  return `
    <div class="campo-senha">
      <input type="password" id="${id}" ${extraAttrs}>
      <button type="button" class="toggle-senha" aria-label="Mostrar senha" tabindex="-1">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <g class="olho-aberto">
            <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"/>
            <circle cx="12" cy="12" r="3"/>
          </g>
          <path class="olho-fechado oculto" d="M3 3l18 18M10.6 10.6a3 3 0 0 0 4.2 4.2M7.4 7.3C4.7 8.9 3 12 3 12s4 7 11 7c1.6 0 3-.4 4.2-1M17.4 17.4C19.9 15.8 21 12 21 12s-1.3-2.3-3.5-4.2"/>
        </svg>
      </button>
    </div>`;
}

// Delegação de evento: funciona para qualquer campo de senha existente na
// página, inclusive os criados dinamicamente dentro de modais.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".toggle-senha");
  if (!btn) return;
  const input = btn.parentElement.querySelector("input");
  const mostrando = input.type === "text";
  input.type = mostrando ? "password" : "text";
  btn.querySelector(".olho-aberto").classList.toggle("oculto", !mostrando);
  btn.querySelector(".olho-fechado").classList.toggle("oculto", mostrando);
  btn.setAttribute("aria-label", mostrando ? "Mostrar senha" : "Ocultar senha");
});

document.getElementById("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value.trim();
  const senha = document.getElementById("login-senha").value;
  const erroEl = document.getElementById("login-erro");
  erroEl.textContent = "";
  try {
    const data = await api("/api/login", { method: "POST", body: JSON.stringify({ email, senha }) });
    state.usuario = data.usuario;
    mostrarApp();
  } catch (err) {
    erroEl.textContent = err.message;
  }
});

document.getElementById("btn-logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

const CHAVE_ULTIMA_TAB = "njc_ultima_tab";

function mostrarApp() {
  document.getElementById("tela-login").classList.add("oculto");
  document.getElementById("app").classList.remove("oculto");
  document.getElementById("usuario-nome").textContent = state.usuario.nome;
  document.getElementById("usuario-perfil").textContent = state.usuario.perfil;
  aplicarPermissoes();

  const tabsAdmin = new Set(["configuracoes"]);
  let tabInicial = localStorage.getItem(CHAVE_ULTIMA_TAB) || "dashboard";
  const tabExiste = !!document.querySelector(`.nav-item[data-tab="${tabInicial}"]`);
  if (!tabExiste || (tabsAdmin.has(tabInicial) && !ehAdmin())) tabInicial = "dashboard";

  ativarTab(tabInicial);
}

// ---------- NAVEGAÇÃO ----------
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => ativarTab(btn.dataset.tab));
});

function ativarTab(nome) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("ativo", b.dataset.tab === nome));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("ativo"));
  document.getElementById(`tab-${nome}`).classList.add("ativo");
  localStorage.setItem(CHAVE_ULTIMA_TAB, nome);
  if (nome === "dashboard") carregarDashboard();
  if (nome === "materiais") carregarMateriais();
  if (nome === "clientes") carregarClientes();
  if (nome === "projetos") carregarProjetos();
  if (nome === "configuracoes") carregarConfiguracoes();
}

document.querySelectorAll(".subnav-item").forEach((btn) => {
  btn.addEventListener("click", () => ativarSubtab(btn.dataset.subtab));
});

function ativarSubtab(nome) {
  document.querySelectorAll(".subnav-item").forEach((b) => b.classList.toggle("ativo", b.dataset.subtab === nome));
  document.querySelectorAll(".subtab").forEach((t) => t.classList.remove("ativo"));
  document.getElementById(`subtab-${nome}`).classList.add("ativo");
  if (nome === "config-auditoria") carregarAuditoria(true);
  if (nome === "config-areas") carregarAreas();
  if (nome === "config-usuarios") carregarUsuarios();
}

function ativarTabInterna(nome) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("ativo"));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("ativo"));
  document.getElementById(`tab-${nome}`).classList.add("ativo");
}

// ---------- DASHBOARD ----------
const CORES_STATUS = {
  conceitual: "var(--viz-serie-1)",
  basico: "var(--viz-serie-3)",
  detalhado: "var(--viz-serie-2)",
};
const ROTULOS_STATUS = {
  conceitual: "Projeto Conceitual", basico: "Projeto Básico", detalhado: "Projeto Detalhado",
};
const ORDEM_STATUS = ["conceitual", "basico", "detalhado"];

async function carregarDashboard() {
  const [materiais, clientes, projetos, resumo] = await Promise.all([
    api("/api/materiais"), api("/api/clientes"), api("/api/projetos"), api("/api/dashboard/resumo"),
  ]);
  document.getElementById("qtd-materiais").textContent = materiais.length;
  document.getElementById("qtd-clientes").textContent = clientes.length;
  document.getElementById("qtd-projetos").textContent = projetos.length;

  renderGraficoStatus(resumo.projetos_por_status);
  renderGraficoFabricantes(resumo.top_fabricantes);
  renderGraficoAtividade(resumo.atividade_por_dia);
}

function renderGraficoStatus(dados) {
  const cont = document.getElementById("grafico-status");
  const total = dados.reduce((s, d) => s + d.total, 0);
  if (!total) {
    cont.innerHTML = `<div class="grafico-vazio">Nenhum projeto cadastrado ainda.</div>`;
    return;
  }
  const ordenado = [...dados].sort((a, b) => ORDEM_STATUS.indexOf(a.status) - ORDEM_STATUS.indexOf(b.status));

  let acumulado = 0;
  const fatias = ordenado.map((d) => {
    const inicio = (acumulado / total) * 360;
    acumulado += d.total;
    const fim = (acumulado / total) * 360;
    return `${CORES_STATUS[d.status] || "var(--viz-ink-muted)"} ${inicio}deg ${fim}deg`;
  }).join(", ");

  const legenda = ordenado.map((d) => `
    <div class="grafico-legenda-item">
      <span class="grafico-legenda-dot" style="background:${CORES_STATUS[d.status] || "var(--viz-ink-muted)"}"></span>
      <span class="grafico-legenda-label">${ROTULOS_STATUS[d.status] || d.status}</span>
      <span class="grafico-legenda-valor">${d.total}</span>
    </div>`).join("");

  cont.innerHTML = `
    <div class="grafico-donut" style="background: conic-gradient(${fatias})" title="Total: ${total} projeto(s)">
      <div class="grafico-donut-total">${total}<small>total</small></div>
    </div>
    <div class="grafico-legenda">${legenda}</div>`;
}

function renderGraficoFabricantes(dados) {
  const cont = document.getElementById("grafico-fabricantes");
  if (!dados.length) {
    cont.innerHTML = `<div class="grafico-vazio">Nenhum material cadastrado ainda.</div>`;
    return;
  }
  const max = Math.max(...dados.map((d) => d.total));
  cont.innerHTML = dados.map((d) => `
    <div class="grafico-barra-linha" title="${d.fabricante}: ${d.total} material(is)">
      <span class="grafico-barra-label">${d.fabricante}</span>
      <span class="grafico-barra-trilho"><span class="grafico-barra-preenchimento" style="width:${(d.total / max) * 100}%"></span></span>
      <span class="grafico-barra-valor">${d.total}</span>
    </div>`).join("");
}

function renderGraficoAtividade(dados) {
  const cont = document.getElementById("grafico-atividade");
  const max = Math.max(1, ...dados.map((d) => d.total));
  cont.innerHTML = dados.map((d) => {
    const dt = new Date(d.data + "T00:00:00");
    const rotulo = dt.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
    return `
      <div class="grafico-coluna-item" title="${rotulo}: ${d.total} evento(s)">
        <div class="grafico-coluna-barra" style="height:${(d.total / max) * 100}%"></div>
        <span class="grafico-coluna-rotulo">${rotulo}</span>
      </div>`;
  }).join("");
}

// ---------- MATERIAIS ----------
const materiaisSelecionados = new Set();
const filtrosColunaMateriais = { codigo: "", descricao: "", fabricante: "", bitola: "", unidade: "", area_nome: "" };

async function carregarMateriais(busca = "") {
  const somenteDuplicados = document.getElementById("check-somente-duplicados").checked;
  const params = new URLSearchParams();
  if (busca) params.set("q", busca);
  if (somenteDuplicados) params.set("somente_duplicados", "1");
  const url = `/api/materiais${params.toString() ? "?" + params.toString() : ""}`;
  state.materiais = await api(url);
  Object.keys(filtrosColunaMateriais).forEach((c) => { filtrosColunaMateriais[c] = ""; });
  popularFiltrosColuna();
  renderizarTabelaMateriais();
}

function popularFiltrosColuna() {
  document.querySelectorAll(".filtro-coluna").forEach((select) => {
    const campo = select.dataset.coluna;
    const valores = [...new Set(state.materiais.map((m) => (m[campo] || "").toString().trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true }));
    select.innerHTML = `<option value="">-- Selecione --</option>` + valores.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    select.value = filtrosColunaMateriais[campo] || "";
  });
}

function renderizarTabelaMateriais() {
  const somenteDuplicados = document.getElementById("check-somente-duplicados").checked;
  materiaisSelecionados.clear();

  const filtrado = state.materiais.filter((m) =>
    Object.entries(filtrosColunaMateriais).every(([campo, valor]) => {
      if (!valor) return true;
      return (m[campo] || "").toString() === valor;
    })
  );
  // Sempre em ordem alfabética crescente por código, inclusive com "somente duplicados" marcado.
  filtrado.sort((a, b) => a.codigo.localeCompare(b.codigo, "pt-BR", { numeric: true }));

  const tbody = document.getElementById("tbody-materiais");
  tbody.innerHTML = filtrado.map((m) => `
    <tr class="${m.duplicado ? "linha-duplicada" : ""}">
      <td class="somente-admin"><input type="checkbox" class="check-material" data-id="${m.id}"></td>
      <td>${esc(m.codigo)}</td>
      <td>${esc(m.descricao)}${m.duplicado ? '<span class="badge-duplicado">Duplicado</span>' : ""}</td>
      <td>${esc(m.fabricante || "")}</td>
      <td>${esc(m.bitola || "")}</td><td>${esc(m.unidade)}</td>
      <td>${esc(m.area_nome || "-")}</td>
      <td class="somente-admin">
        <button class="link-acao" onclick="editarMaterial(${m.id})">Editar</button>
        <button class="link-acao" onclick="excluirMaterial(${m.id})">Excluir</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="8">${somenteDuplicados ? "Nenhum material duplicado encontrado." : "Nenhum material encontrado."}</td></tr>`;
  document.getElementById("check-todos-materiais").checked = false;
  atualizarBotaoExclusaoLote();
  document.querySelectorAll(".check-material").forEach((chk) => {
    chk.addEventListener("change", () => {
      const id = Number(chk.dataset.id);
      if (chk.checked) materiaisSelecionados.add(id);
      else materiaisSelecionados.delete(id);
      atualizarBotaoExclusaoLote();
    });
  });
  aplicarPermissoes();
}

document.querySelectorAll(".filtro-coluna").forEach((select) => {
  select.addEventListener("change", () => {
    filtrosColunaMateriais[select.dataset.coluna] = select.value;
    renderizarTabelaMateriais();
  });
});

function atualizarBotaoExclusaoLote() {
  const btn = document.getElementById("btn-excluir-selecionados");
  document.getElementById("qtd-selecionados").textContent = materiaisSelecionados.size;
  btn.classList.toggle("oculto", materiaisSelecionados.size === 0);
}

document.getElementById("check-todos-materiais").addEventListener("change", (e) => {
  document.querySelectorAll(".check-material").forEach((chk) => {
    chk.checked = e.target.checked;
    const id = Number(chk.dataset.id);
    if (e.target.checked) materiaisSelecionados.add(id);
    else materiaisSelecionados.delete(id);
  });
  atualizarBotaoExclusaoLote();
});

document.getElementById("btn-excluir-selecionados").addEventListener("click", async () => {
  const qtd = materiaisSelecionados.size;
  if (!qtd) return;
  if (!(await confirmarPersonalizado(`Excluir ${qtd} material(is) selecionado(s)? Esta ação não pode ser desfeita.`))) return;
  try {
    await api("/api/materiais/excluir-lote", { method: "POST", body: JSON.stringify({ ids: [...materiaisSelecionados] }) });
    toast(`${qtd} material(is) excluído(s)`);
    carregarMateriais(document.getElementById("materiais-busca").value);
  } catch (err) { toast(err.message, "erro"); }
});

let buscaMateriaisTimer;
document.getElementById("materiais-busca").addEventListener("input", (e) => {
  clearTimeout(buscaMateriaisTimer);
  buscaMateriaisTimer = setTimeout(() => carregarMateriais(e.target.value), 300);
});

document.getElementById("check-somente-duplicados").addEventListener("change", () => {
  carregarMateriais(document.getElementById("materiais-busca").value);
});

async function modalMaterial(material = null) {
  await garantirAreasCarregadas();
  const m = material || { codigo: "", descricao: "", fabricante: "", bitola: "", unidade: "", area_id: "" };
  const opcoesAreas = state.areas.map((a) => `<option value="${a.id}" ${m.area_id == a.id ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
  abrirModal(`
    <h3>${material ? "Editar" : "Novo"} Material</h3>
    <div class="form-grid">
      <label>Código</label><input id="mat-codigo" value="${esc(m.codigo)}">
      <label>Descrição</label><input id="mat-descricao" value="${esc(m.descricao)}">
      <label>Fabricante</label><input id="mat-fabricante" value="${esc(m.fabricante || "")}">
      <label>Bitola</label><input id="mat-bitola" value="${esc(m.bitola || "")}">
      <label>Unidade</label><input id="mat-unidade" value="${esc(m.unidade)}">
      <label>Área</label>
      <select id="mat-area"><option value="">-- Selecione --</option>${opcoesAreas}</select>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario" onclick="salvarMaterial(${material ? material.id : "null"})">Salvar</button>
    </div>
  `);
}

async function salvarMaterial(id) {
  const payload = {
    codigo: document.getElementById("mat-codigo").value.trim(),
    descricao: document.getElementById("mat-descricao").value.trim(),
    fabricante: document.getElementById("mat-fabricante").value.trim(),
    bitola: document.getElementById("mat-bitola").value.trim(),
    unidade: document.getElementById("mat-unidade").value.trim(),
    area_id: Number(document.getElementById("mat-area").value) || null,
  };
  if (!payload.area_id) { toast("Selecione a área do material", "erro"); return; }
  try {
    if (id) await api(`/api/materiais/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await api("/api/materiais", { method: "POST", body: JSON.stringify(payload) });
    fecharModal();
    toast("Material salvo com sucesso");
    carregarMateriais();
  } catch (err) { toast(err.message, "erro"); }
}

function editarMaterial(id) {
  const m = state.materiais.find((x) => x.id === id);
  modalMaterial(m);
}

async function excluirMaterial(id) {
  if (!(await confirmarPersonalizado("Excluir este material?"))) return;
  await api(`/api/materiais/${id}`, { method: "DELETE" });
  toast("Material excluído");
  carregarMateriais();
}

document.getElementById("btn-novo-material").addEventListener("click", () => modalMaterial());

document.getElementById("btn-importar-excel").addEventListener("click", () => {
  document.getElementById("input-importar").click();
});

document.getElementById("input-importar").addEventListener("change", async (e) => {
  const arquivo = e.target.files[0];
  if (!arquivo) return;
  e.target.value = "";
  await garantirAreasCarregadas();
  if (!state.areas.length) {
    toast("Cadastre uma área em Configurações antes de importar materiais", "erro");
    return;
  }
  mostrarModalEscolherArea(arquivo);
});

function mostrarModalEscolherArea(arquivo) {
  const opcoesAreas = state.areas.map((a) => `<option value="${a.id}">${esc(a.nome)}</option>`).join("");
  abrirModal(`
    <h3>Importar materiais</h3>
    <div class="form-grid">
      <label>Área de destino</label>
      <select id="importar-area">${opcoesAreas}</select>
      <p style="color:var(--cinza); font-size:12.5px; margin:0;">Todos os materiais desta planilha serão vinculados à área escolhida.</p>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario" id="btn-continuar-importacao">Continuar</button>
    </div>
  `);
  document.getElementById("btn-continuar-importacao").addEventListener("click", async () => {
    const areaId = Number(document.getElementById("importar-area").value);
    fecharModal();
    try {
      const formData = new FormData();
      formData.append("arquivo", arquivo);
      const analise = await api("/api/materiais/importar/excel/analisar", { method: "POST", body: formData });
      if (analise.duplicados.length > 0) {
        mostrarModalDuplicados(analise, arquivo, areaId);
      } else {
        await executarImportacao(arquivo, areaId);
      }
    } catch (err) { toast(err.message, "erro"); }
  });
}

function mostrarModalDuplicados(analise, arquivo, areaId) {
  const conflitos = analise.duplicados.filter((d) => d.conflito).length;
  const linhasDuplicado = (d) => `
    <div style="margin-bottom:10px; padding:8px 10px; border-radius:6px; background:${d.conflito ? "#fdeceb" : "#f2f4f7"};">
      <div><b>${esc(d.codigo)}</b> — linhas ${d.linhas.join(", ")}
        ${d.conflito ? '<span style="color:var(--erro); font-weight:600;"> ⚠ dados diferentes entre as linhas</span>' : '<span style="color:var(--cinza);"> (dados idênticos)</span>'}
      </div>
      ${d.conflito ? `<table class="tabela" style="margin-top:6px; font-size:11.5px;">
        <thead><tr><th>Linha</th><th>Descrição</th><th>Fabricante</th><th>Bitola</th><th>Unidade</th></tr></thead>
        <tbody>
          ${d.ocorrencias.map((o) => `<tr><td>${o.linha}</td><td>${esc(o.descricao)}</td><td>${esc(o.fabricante)}</td><td>${esc(o.bitola)}</td><td>${esc(o.unidade)}</td></tr>`).join("")}
        </tbody>
      </table>` : ""}
    </div>`;

  abrirModal(`
    <h3>Códigos repetidos encontrados na planilha</h3>
    <p style="color:var(--cinza); font-size:13px;">
      ${analise.total_linhas} linha(s) lida(s), ${analise.codigos_unicos} código(s) único(s),
      ${analise.duplicados.length} código(s) repetido(s)${conflitos ? ` — <b style="color:var(--erro)">${conflitos} com dados divergentes</b>` : ""}.
    </p>
    <div style="max-height:300px; overflow-y:auto; margin:12px 0;">
      ${analise.duplicados.map(linhasDuplicado).join("")}
    </div>
    <div class="modal-acoes" style="flex-wrap:wrap;">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <span style="flex:1"></span>
      <button class="btn-secundario" id="btn-importar-sem-duplicadas">Importar sem as duplicadas</button>
      <button class="btn-primario" id="btn-importar-com-duplicadas">Importar com as duplicadas</button>
    </div>
  `, "modal-grande");

  document.getElementById("btn-importar-com-duplicadas").addEventListener("click", async () => {
    fecharModal();
    await executarImportacao(arquivo, areaId, "manter");
  });
  document.getElementById("btn-importar-sem-duplicadas").addEventListener("click", async () => {
    fecharModal();
    await executarImportacao(arquivo, areaId, "excluir");
  });
}

async function executarImportacao(arquivo, areaId, modoDuplicados = "manter") {
  const formData = new FormData();
  formData.append("arquivo", arquivo);
  formData.append("area_id", areaId);
  formData.append("duplicados", modoDuplicados);
  try {
    const r = await api("/api/materiais/importar/excel", { method: "POST", body: formData });
    abrirModal(`
      <h3>Importação concluída</h3>
      <div class="form-grid">
        <p>Linhas lidas na planilha: <b>${r.total_linhas}</b></p>
        <p>Materiais novos: <b>${r.inseridos}</b></p>
        <p>Materiais atualizados: <b>${r.atualizados}</b></p>
        <p>Linhas ignoradas (sem código): <b>${r.ignoradas}</b></p>
        ${r.duplicados_excluidos ? `<p>Linhas excluídas por duplicidade de código: <b>${r.duplicados_excluidos}</b></p>` : ""}
      </div>
      <div class="modal-acoes">
        <button class="btn-primario" onclick="fecharModalComConfirmacao()">Ok</button>
      </div>
    `, "");
    carregarMateriais();
  } catch (err) { toast(err.message, "erro"); }
}

// ---------- CLIENTES ----------
async function carregarClientes(busca = "") {
  const url = busca ? `/api/clientes?q=${encodeURIComponent(busca)}` : "/api/clientes";
  state.clientes = await api(url);
  renderTabelaClientes();
}

// Clientes com o dropdown de projetos aberto no momento (sobrevive a
// re-renders da tabela, ex.: ao editar outro cliente).
const clientesExpandidos = new Set();

function renderTabelaClientes() {
  const tbody = document.getElementById("tbody-clientes");
  tbody.innerHTML = state.clientes.map((c) => {
    const aberto = clientesExpandidos.has(c.id);
    const linhaDropdown = aberto ? `
      <tr class="linha-dropdown-projetos">
        <td colspan="6">${htmlProjetosDoCliente(c.id)}</td>
      </tr>` : "";
    return `
      <tr class="linha-clicavel" onclick="toggleProjetosDoCliente(${c.id})">
        <td><span class="seta-expandir ${aberto ? "aberta" : ""}">${ICONE_SETA}</span>${esc(c.razao_social)}</td>
        <td>${esc(c.nome_fantasia || "")}</td><td>${esc(c.cnpj_cpf || "")}</td>
        <td>${esc(c.contato || "")}</td><td>${esc(c.telefone || "")}</td>
        <td class="somente-admin">
          <button class="link-acao" onclick="event.stopPropagation(); editarCliente(${c.id})">Editar</button>
          <button class="link-acao" onclick="event.stopPropagation(); excluirCliente(${c.id})">Excluir</button>
        </td>
      </tr>${linhaDropdown}`;
  }).join("") || `<tr><td colspan="6">Nenhum cliente cadastrado.</td></tr>`;
  aplicarPermissoes();
}

function htmlProjetosDoCliente(clienteId) {
  const doCliente = state.projetos.filter((p) => p.cliente_id === clienteId);
  if (!doCliente.length) return `<div class="arvore-carregando">Este cliente ainda não tem projetos cadastrados.</div>`;
  return `
    <div class="dropdown-projetos-cliente">
      ${doCliente.map((p) => `
        <div class="dropdown-projeto-linha">
          <span><b>${esc(p.codigo)}</b> — ${esc(p.nome)} <span class="arvore-sub">${esc(p.status)} · ${esc(p.area_nome || "-")}</span></span>
          <button class="link-acao" onclick="event.stopPropagation(); abrirProjeto(${p.id})">Abrir</button>
        </div>`).join("")}
    </div>`;
}

// Ao clicar num cliente, expande/recolhe um dropdown com os projetos dele
// direto na linha - útil pra achar rápido o histórico de um cliente sem
// precisar procurar na lista de projetos.
async function toggleProjetosDoCliente(clienteId) {
  if (clientesExpandidos.has(clienteId)) {
    clientesExpandidos.delete(clienteId);
    renderTabelaClientes();
    return;
  }
  clientesExpandidos.add(clienteId);
  if (!state.projetos.length) state.projetos = await api("/api/projetos");
  renderTabelaClientes();
}

let buscaClientesTimer;
document.getElementById("clientes-busca").addEventListener("input", (e) => {
  clearTimeout(buscaClientesTimer);
  buscaClientesTimer = setTimeout(() => carregarClientes(e.target.value), 300);
});

function modalCliente(cliente = null) {
  const c = cliente || { razao_social: "", nome_fantasia: "", cnpj_cpf: "", contato: "", telefone: "", email: "", endereco: "", logo_url: "" };
  abrirModal(`
    <h3>${cliente ? "Editar" : "Novo"} Cliente</h3>
    <div class="form-grid">
      <label>Razão Social</label><input id="cli-razao" value="${esc(c.razao_social)}">
      <label>Nome Fantasia</label><input id="cli-fantasia" value="${esc(c.nome_fantasia || "")}">
      <label>CNPJ/CPF</label><input id="cli-doc" value="${esc(c.cnpj_cpf || "")}">
      <label>Contato</label><input id="cli-contato" value="${esc(c.contato || "")}">
      <label>Telefone</label><input id="cli-telefone" value="${esc(c.telefone || "")}">
      <label>Email</label><input id="cli-email" value="${esc(c.email || "")}">
      <label>Endereço</label><input id="cli-endereco" value="${esc(c.endereco || "")}">
      <label>URL da Logo</label><input id="cli-logo" value="${esc(c.logo_url || "")}" placeholder="https://...">
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario" onclick="salvarCliente(${cliente ? cliente.id : "null"})">Salvar</button>
    </div>
  `);
}

async function salvarCliente(id) {
  const payload = {
    razao_social: document.getElementById("cli-razao").value.trim(),
    nome_fantasia: document.getElementById("cli-fantasia").value.trim(),
    cnpj_cpf: document.getElementById("cli-doc").value.trim(),
    contato: document.getElementById("cli-contato").value.trim(),
    telefone: document.getElementById("cli-telefone").value.trim(),
    email: document.getElementById("cli-email").value.trim(),
    endereco: document.getElementById("cli-endereco").value.trim(),
    logo_url: document.getElementById("cli-logo").value.trim(),
  };
  try {
    if (id) await api(`/api/clientes/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await api("/api/clientes", { method: "POST", body: JSON.stringify(payload) });
    fecharModal();
    toast("Cliente salvo com sucesso");
    carregarClientes();
  } catch (err) { toast(err.message, "erro"); }
}

function editarCliente(id) {
  modalCliente(state.clientes.find((x) => x.id === id));
}

async function excluirCliente(id) {
  if (!(await confirmarPersonalizado("Excluir este cliente?"))) return;
  await api(`/api/clientes/${id}`, { method: "DELETE" });
  toast("Cliente excluído");
  carregarClientes();
}

document.getElementById("btn-novo-cliente").addEventListener("click", () => modalCliente());

// ---------- PROJETOS ----------
async function carregarProjetos() {
  state.projetos = await api("/api/projetos");
  const tbody = document.getElementById("tbody-projetos");
  tbody.innerHTML = state.projetos.map((p) => `
    <tr>
      <td>${esc(p.codigo)}</td><td>${esc(p.nome)}</td><td>${esc(p.cliente_nome || "-")}</td><td>${esc(p.status)}</td><td>${esc(p.area_nome || "-")}</td>
      <td class="acoes-linha">
        <button class="link-acao" onclick="abrirProjeto(${p.id})">Abrir</button>
        <button class="link-acao somente-admin" onclick="editarProjeto(${p.id})">Editar</button>
        <button class="link-acao somente-master" onclick="excluirProjeto(${p.id})">Excluir</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="6">Nenhum projeto cadastrado.</td></tr>`;
  aplicarPermissoes();
}

async function excluirProjeto(id) {
  if (!(await confirmarPersonalizado("Excluir este projeto e todo o seu histórico de listas, PQ e compras?"))) return;
  try {
    await api(`/api/projetos/${id}`, { method: "DELETE" });
    toast("Projeto excluído");
    carregarProjetos();
  } catch (err) { toast(err.message, "erro"); }
}

async function modalProjeto(projeto = null) {
  if (!state.clientes.length) state.clientes = await api("/api/clientes");
  await garantirAreasCarregadas();
  const p = projeto || { codigo: "", nome: "", cliente_id: "", status: "conceitual", numero_cliente: "", numero_fornecedor: "", area_id: "" };
  const opcoesClientes = state.clientes.map((c) => `<option value="${c.id}" ${p.cliente_id == c.id ? "selected" : ""}>${esc(c.nome_fantasia || c.razao_social)}</option>`).join("");
  const opcoesAreas = state.areas.map((a) => `<option value="${a.id}" ${p.area_id == a.id ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
  abrirModal(`
    <h3>${projeto ? "Editar" : "Novo"} Projeto</h3>
    <div class="form-grid">
      <label>Cliente</label>
      <select id="proj-cliente"><option value="">-- Selecione --</option>${opcoesClientes}</select>
      <label>Número do Projeto</label><input id="proj-nome" value="${esc(p.nome)}">
      <label>Status</label>
      <select id="proj-status">
        ${ORDEM_STATUS.map((s) => `<option value="${s}" ${p.status === s ? "selected" : ""}>${ROTULOS_STATUS[s]}</option>`).join("")}
      </select>
      <label>Código</label><input id="proj-codigo" value="${esc(p.codigo)}">
      <label>Nº do Cliente</label><input id="proj-numero-cliente" value="${esc(p.numero_cliente || "")}">
      <label>Nº do Fornecedor</label><input id="proj-numero-fornecedor" value="${esc(p.numero_fornecedor || "")}">
      <label>Área</label>
      <select id="proj-area"><option value="">-- Selecione --</option>${opcoesAreas}</select>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario" onclick="salvarProjeto(${projeto ? projeto.id : "null"})">Salvar</button>
    </div>
  `);
}

async function salvarProjeto(id) {
  const payload = {
    cliente_id: document.getElementById("proj-cliente").value || null,
    nome: document.getElementById("proj-nome").value.trim(),
    status: document.getElementById("proj-status").value,
    codigo: document.getElementById("proj-codigo").value.trim(),
    numero_cliente: document.getElementById("proj-numero-cliente").value.trim(),
    numero_fornecedor: document.getElementById("proj-numero-fornecedor").value.trim(),
    area_id: Number(document.getElementById("proj-area").value) || null,
  };
  if (!payload.cliente_id) { toast("Selecione o cliente", "erro"); return; }
  if (!payload.area_id) { toast("Selecione a área", "erro"); return; }
  try {
    if (id) await api(`/api/projetos/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await api("/api/projetos", { method: "POST", body: JSON.stringify(payload) });
    fecharModal();
    toast("Projeto salvo com sucesso");
    carregarProjetos();
  } catch (err) { toast(err.message, "erro"); }
}

function editarProjeto(id) {
  modalProjeto(state.projetos.find((x) => x.id === id));
}

document.getElementById("btn-novo-projeto").addEventListener("click", () => modalProjeto());
document.getElementById("btn-voltar-projetos").addEventListener("click", () => ativarTabInterna("projetos"));

// ---------- LISTAS POR DESENHO ----------
async function abrirProjeto(id) {
  state.projetoAtual = state.projetos.find((p) => p.id === id);
  document.getElementById("projeto-detalhe-titulo").textContent = `${state.projetoAtual.codigo} — ${state.projetoAtual.nome}`;
  document.getElementById("link-relatorio-projeto-excel").href = `/api/projetos/${id}/relatorio/excel`;
  document.getElementById("link-relatorio-projeto-pdf").href = `/api/projetos/${id}/relatorio/pdf`;
  document.getElementById("link-relatorio-pq-excel").href = `/api/projetos/${id}/lista-pq/relatorio/excel`;
  document.getElementById("link-relatorio-pq-pdf").href = `/api/projetos/${id}/lista-pq/relatorio/pdf`;
  document.getElementById("link-relatorio-compras-excel").href = `/api/projetos/${id}/lista-compras/relatorio/excel`;
  document.getElementById("link-relatorio-compras-pdf").href = `/api/projetos/${id}/lista-compras/relatorio/pdf`;
  ativarTabInterna("projeto-detalhe");
  ativarSubtabPD("pd-desenho");
  await carregarListas(id);
}

document.querySelectorAll(".subnav-item-pd").forEach((btn) => {
  btn.addEventListener("click", () => ativarSubtabPD(btn.dataset.subtabPd));
});

function ativarSubtabPD(nome) {
  document.querySelectorAll(".subnav-item-pd").forEach((b) => b.classList.toggle("ativo", b.dataset.subtabPd === nome));
  document.querySelectorAll(".subtab-pd").forEach((t) => t.classList.remove("ativo"));
  document.getElementById(`subtab-${nome}`).classList.add("ativo");
  if (nome === "pd-pq") {
    document.getElementById("btn-criar-pq").classList.remove("oculto");
    document.getElementById("btn-revisar-pq").classList.add("oculto");
    carregarListaPQ();
  }
  if (nome === "pd-compras") {
    document.getElementById("btn-criar-compras").classList.remove("oculto");
    document.getElementById("btn-revisar-compras").classList.add("oculto");
    carregarListaCompras();
  }
}

document.getElementById("btn-criar-pq").addEventListener("click", async () => {
  const listas = await api(`/api/projetos/${state.projetoAtual.id}/listas`);
  if (!listas.length) { toast("Este projeto ainda não tem nenhuma Lista por Desenho cadastrada", "erro"); return; }
  abrirSelecaoListas(
    "Selecionar Listas para a Planilha de Quantidades",
    "Escolha quais Listas por Desenho entrarão na consolidação da Planilha de Quantidades. Por padrão, todas estão marcadas.",
    listas,
    (selecionados) => {
      window._pqListaIdsSelecionados = selecionados;
      document.getElementById("btn-criar-pq").classList.add("oculto");
      document.getElementById("btn-revisar-pq").classList.remove("oculto");
    },
  );
});

// Modal genérico de checklist de listas por desenho, reaproveitado por PQ e Compras.
function abrirSelecaoListas(titulo, mensagem, listas, aoConfirmar) {
  const linhas = listas.map((l) => `
    <label class="selecao-lista-linha">
      <input type="checkbox" class="selecao-lista-check" value="${l.id}" checked>
      <span>${esc(l.numero_cliente || "-")} / ${esc(l.numero_fornecedor || "-")}${l.titulo ? " — " + esc(l.titulo) : ""} <span class="arvore-sub">(${esc(l.numero_desenho)})</span></span>
    </label>`).join("");
  abrirModal(`
    <h3>${titulo}</h3>
    <p style="color:var(--cinza); font-size:13px;">${mensagem}</p>
    <div class="selecao-lista-wrap">${linhas}</div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario" id="btn-continuar-selecao-listas">Continuar</button>
    </div>
  `);
  document.getElementById("btn-continuar-selecao-listas").addEventListener("click", () => {
    const selecionados = Array.from(document.querySelectorAll(".selecao-lista-check:checked")).map((c) => Number(c.value));
    if (!selecionados.length) { toast("Selecione ao menos uma lista", "erro"); return; }
    fecharModal();
    aoConfirmar(selecionados);
  });
}

document.getElementById("btn-criar-compras").addEventListener("click", async () => {
  const dadosPQ = await api(`/api/projetos/${state.projetoAtual.id}/lista-pq`);
  if (!dadosPQ.versao) { toast("A Planilha de Quantidades deste projeto ainda não tem nenhuma versão salva", "erro"); return; }
  const versaoPQ = await api(`/api/lista-pq/versoes/${dadosPQ.versao.id}`);
  const origens = versaoPQ.versao.origens || [];
  if (!origens.length) { toast("Esta versão da Planilha de Quantidades não tem listas de origem registradas", "erro"); return; }
  abrirSelecaoListas(
    "Selecionar Listas para a Lista de Compras",
    "Escolha quais listas por desenho (que compõem a Planilha de Quantidades atual) entrarão na Lista de Compras. Por padrão, todas estão marcadas.",
    origens.map((o) => ({ id: o.lista_desenho_id, numero_desenho: o.numero_desenho, titulo: o.titulo })),
    (selecionados) => {
      window._comprasListaIdsSelecionados = selecionados;
      document.getElementById("btn-criar-compras").classList.add("oculto");
      document.getElementById("btn-revisar-compras").classList.remove("oculto");
    },
  );
});

const arvoreState = { listas: [], versoesPorLista: {}, expandidas: new Set() };

async function carregarListas(projetoId) {
  arvoreState.listas = await api(`/api/projetos/${projetoId}/listas`);
  arvoreState.versoesPorLista = {};
  arvoreState.expandidas.clear();
  renderArvoreListas();
}

function renderArvoreListas() {
  const cont = document.getElementById("arvore-listas");
  if (!arvoreState.listas.length) {
    cont.innerHTML = `<div class="arvore-vazio">Nenhuma lista cadastrada para este projeto.</div>`;
    return;
  }
  cont.innerHTML = arvoreState.listas.map(renderNoLista).join("");
  aplicarPermissoes();
}

const ICONE_PASTA = `<svg class="arvore-icone" viewBox="0 0 20 20" fill="none"><path d="M2.5 5.5a1 1 0 0 1 1-1h4l1.5 1.8h7.5a1 1 0 0 1 1 1v8.2a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1V5.5Z" fill="currentColor" fill-opacity=".14" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>`;
const ICONE_ARQUIVO = `<svg class="arvore-icone" viewBox="0 0 20 20" fill="none"><path d="M6 2.5h6l3 3v10a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1Z" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M12 2.5V6h3" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>`;
const ICONE_SETA = `<svg viewBox="0 0 12 12" fill="none"><path d="M4 2.5 8 6l-4 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICONE_LAPIS = `<svg viewBox="0 0 20 20" fill="none"><path d="M13.4 3.3a1.6 1.6 0 0 1 2.3 0l1 1a1.6 1.6 0 0 1 0 2.3L7.4 15.9l-4 .8.8-4 9.2-9.4Z" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M11.9 4.8l3.3 3.3" stroke="currentColor" stroke-width="1.3"/></svg>`;
const ICONE_IMPRIMIR = `<svg viewBox="0 0 20 20" fill="none"><path d="M6.3 3.3h7.4v4H6.3z" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-width="1.25" stroke-linejoin="round"/><rect x="3" y="7.3" width="14" height="6.7" rx="1.3" fill="currentColor" fill-opacity=".06" stroke="currentColor" stroke-width="1.25"/><rect x="6.3" y="10.6" width="7.4" height="5.7" fill="currentColor" fill-opacity=".08" stroke="currentColor" stroke-width="1.15"/><circle cx="14.1" cy="9.5" r=".75" fill="currentColor"/></svg>`;
const ICONE_EXCLUIR = `<svg viewBox="0 0 20 20" fill="none"><path d="M5 5l10 10M15 5 5 15" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`;

function renderNoLista(l) {
  const aberta = arvoreState.expandidas.has(l.id);
  const versoes = arvoreState.versoesPorLista[l.id];
  return `
    <div class="arvore-no" data-lista-id="${l.id}">
      <div class="arvore-linha arvore-linha-pasta">
        <button class="arvore-toggle ${aberta ? "aberto" : ""}" onclick="toggleListaArvore(${l.id})" aria-label="Expandir">
          <svg viewBox="0 0 12 12" fill="none"><path d="M4 2.5 8 6l-4 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        ${ICONE_PASTA}
        <span class="arvore-label" onclick="toggleListaArvore(${l.id})">
          <span class="arvore-titulo">${esc(l.numero_cliente || "-")} / ${esc(l.numero_fornecedor || "-")}${l.titulo ? " — " + esc(l.titulo) : ""}</span>
          <span class="arvore-sub">${l.versao_atual ? "v" + l.versao_atual : "sem versão emitida"}${l.tem_rascunho ? '<span class="badge-rascunho">Rascunho em aberto</span>' : ""}</span>
        </span>
        <span class="arvore-acoes">
          <button class="link-acao" onclick="abrirEditorMateriais(${l.id})">Editar materiais</button>
          <a class="acao-icone" href="/api/listas/${l.id}/relatorio/excel" target="_blank" title="Baixar Excel" aria-label="Baixar Excel">${ICONE_IMPRIMIR}</a>
          <button class="acao-icone somente-admin" onclick="abrirEditorDados(${l.id})" title="Editar dados" aria-label="Editar dados">${ICONE_LAPIS}</button>
          <button class="acao-icone acao-perigo somente-master" onclick="excluirLista(${l.id})" title="Excluir" aria-label="Excluir">${ICONE_EXCLUIR}</button>
        </span>
      </div>
      <div class="arvore-filhos ${aberta ? "" : "oculto"}" id="filhos-lista-${l.id}">
        ${aberta ? renderFilhosVersoes(l.id, versoes) : ""}
      </div>
    </div>`;
}

function renderFilhosVersoes(listaId, versoes) {
  if (!versoes) return `<div class="arvore-carregando">Carregando versões…</div>`;
  if (!versoes.length) return `<div class="arvore-carregando">Nenhuma versão salva.</div>`;
  return versoes.map((v) => `
    <div class="arvore-linha arvore-linha-versao">
      <span class="arvore-toggle invisivel"></span>
      ${ICONE_ARQUIVO}
      <span class="arvore-label" onclick="verVersao(${listaId}, ${v.id})">
        <span class="arvore-titulo">v${v.versao}${v.status === "rascunho" ? '<span class="badge-rascunho">Rascunho</span>' : ""}</span>
        <span class="arvore-sub">${new Date(v.criado_em).toLocaleString("pt-BR")} · ${esc(v.criado_por_nome || "-")}</span>
      </span>
      <span class="arvore-acoes">
        ${v.status === "rascunho" ? `<button class="link-acao somente-admin" onclick="abrirEditorMateriais(${listaId})">Editar rascunho</button>` : ""}
        <button class="link-acao" onclick="verVersao(${listaId}, ${v.id})">Ver</button>
      </span>
    </div>`).join("");
}

async function toggleListaArvore(listaId) {
  if (arvoreState.expandidas.has(listaId)) {
    arvoreState.expandidas.delete(listaId);
    renderArvoreListas();
    return;
  }
  arvoreState.expandidas.add(listaId);
  if (!arvoreState.versoesPorLista[listaId]) {
    renderArvoreListas();
    arvoreState.versoesPorLista[listaId] = await api(`/api/listas/${listaId}/versoes`);
  }
  renderArvoreListas();
}

// Confirmação por senha para ações destrutivas restritas a master (ex.:
// excluir uma pasta/lista por desenho). Diferente da Zona de Risco (que
// pede para digitar uma palavra), aqui reautentica a própria pessoa.
function confirmarComSenha(titulo, mensagem, aoConfirmar) {
  abrirModal(`
    <h3>${titulo}</h3>
    <p style="color:var(--cinza);">${mensagem}</p>
    <p>Digite sua senha para confirmar:</p>
    ${campoSenhaHtml("confirmar-senha-input", 'autocomplete="current-password"')}
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-perigo" id="btn-confirmar-senha">${titulo}</button>
    </div>
  `);
  const input = document.getElementById("confirmar-senha-input");
  input.focus();
  document.getElementById("btn-confirmar-senha").addEventListener("click", async () => {
    const senha = input.value;
    if (!senha) { toast("Informe sua senha", "erro"); return; }
    try {
      await aoConfirmar(senha);
      fecharModal();
    } catch (err) { toast(err.message, "erro"); }
  });
}

function excluirLista(id) {
  confirmarComSenha(
    "Excluir lista por desenho",
    "Esta lista por desenho e todo o seu histórico de versões serão removidos. Essa ação não pode ser desfeita.",
    async (senha) => {
      await api(`/api/listas/${id}`, { method: "DELETE", body: JSON.stringify({ senha }) });
      toast("Lista excluída");
      carregarListas(state.projetoAtual.id);
    },
  );
}

// A lista só é criada no banco quando a primeira versão (com os itens
// escolhidos) é salva - assim não sobra uma "v1" vazia no histórico.
document.getElementById("btn-nova-lista").addEventListener("click", async () => {
  if (!state.materiais.length) state.materiais = await api("/api/materiais");
  window._itensEditor = [];
  renderCabecalhoLista(null, {});
});

// Monta o rótulo de um material com código e bitola em destaque (linha 1)
// e a descrição completa como texto secundário (linha 2) - sem isso, dois
// materiais com a mesma descrição e bitolas diferentes (ex.: cabos de
// mesma família em calibres distintos) ficam indistinguíveis na busca.
function _rotuloMaterialHtml(m) {
  const bitola = m.bitola ? `<span class="badge-bitola">${esc(m.bitola)}</span>` : "";
  return `
    <span class="material-rotulo">
      <span class="material-codigo">${esc(m.codigo)}</span>${bitola}
      <span class="material-descricao">${esc(m.descricao)}</span>
    </span>`;
}

// Escapa caracteres especiais de HTML (ex.: "<", ">") antes de inserir texto
// vindo do banco (descrições de materiais) via innerHTML - sem isso, uma
// descrição contendo "<" quebra a estrutura da página.
function escapeHtml(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
// Alias curto (função declarada = hoisted, seguro em qualquer ponto do arquivo)
function esc(texto) { return escapeHtml(texto); }

// Normaliza uma data vinda da API (ISO ou formato HTTP) pro formato que o
// <input type="date"> exige (YYYY-MM-DD), sem quebrar se vier vazia/inválida.
function paraDataInput(valor) {
  if (!valor) return "";
  const d = new Date(valor);
  return isNaN(d) ? "" : d.toISOString().slice(0, 10);
}

// ---------- EDITOR DA LISTA (com versionamento) ----------
// Acesso separado do editor de materiais: só os dados da pasta (título,
// cliente/fornecedor, carimbo), salvos direto via /cabecalho, sem tocar em
// versões/itens.
async function abrirEditorDados(listaId) {
  const dados = await api(`/api/listas/${listaId}`);
  renderCabecalhoLista(listaId, dados.lista, true);
}

async function abrirEditorMateriais(listaId) {
  if (!state.materiais.length) state.materiais = await api("/api/materiais");
  const dados = await api(`/api/listas/${listaId}`);
  const temRascunho = !!dados.rascunho;
  const itensBase = temRascunho ? dados.itens_rascunho : dados.itens;
  const itensIniciais = itensBase.map((i) => ({
    material_id: i.material_id, codigo: i.codigo, descricao: i.descricao,
    fabricante: i.fabricante, bitola: i.bitola, unidade: i.unidade,
    quantidade: Math.round(Number(i.quantidade)) || 0, observacao: i.observacao || "",
  }));
  window._itensEditor = itensIniciais;

  if (temRascunho) toast(`Continuando o rascunho salvo em ${new Date(dados.rascunho.criado_em).toLocaleString("pt-BR")}`);
  renderEditorLista(listaId, dados.lista);
}

async function salvarCabecalhoLista(listaId, cabecalho) {
  try {
    await api(`/api/listas/${listaId}/cabecalho`, { method: "PUT", body: JSON.stringify(cabecalho) });
    toast("Dados da pasta salvos");
    fecharModal();
    carregarListas(state.projetoAtual.id);
  } catch (err) { toast(err.message, "erro"); }
}

// TELA 1: cabeçalho (título, cliente/fornecedor, desenho de referência, carimbo).
// somenteDados=true: edição isolada da pasta (botão "Salvar", persiste na hora).
// somenteDados=false: primeiro passo do fluxo de criação/edição de materiais
// (botão "Continuar", segue para a Tela 2 sem salvar nada ainda).
function renderCabecalhoLista(listaId, lista, somenteDados = false) {
  abrirModal(`
    <h3>${lista.numero_desenho ? `Lista por Desenho — ${esc(lista.numero_desenho)}` : "Nova Lista por Desenho"}</h3>
    <div class="form-grid-lista">
      <div class="campo-linha"><label>Subtítulo (linha 1 do carimbo)</label><input id="cab-subtitulo" value="${esc(lista.subtitulo || "")}" placeholder="Ex.: ENGENHARIA DETALHADA - UTM"></div>
      <div class="campo-linha"><label>Área (linha 2 do carimbo)</label><input id="cab-area-titulo" value="${esc(lista.area_titulo || "")}" placeholder="Ex.: ÁREA 3110 - BRITAGEM PRIMÁRIA"></div>
      <div class="campo-linha"><label>Disciplina (linha 3 do carimbo)</label><input id="cab-disciplina" value="${esc(lista.disciplina || "")}" placeholder="Ex.: ELÉTRICA"></div>
      <div class="campo-linha"><label>Título do Documento (linha 4 do carimbo)</label><input id="cab-titulo" value="${esc(lista.titulo || "")}"></div>
      <div class="campo-linha campo-dupla">
        <div><label>Número do Cliente</label><input id="cab-numero-cliente" value="${esc(lista.numero_cliente || "")}"></div>
        <div><label>Número do Projetista</label><input id="cab-numero-fornecedor" value="${esc(lista.numero_fornecedor || "")}"></div>
      </div>
      <div class="campo-linha"><label>Número do Desenho de Referência</label><input id="cab-numero-desenho" value="${esc(lista.numero_desenho || "")}"></div>
      <div class="campo-linha campo-dupla">
        <div><label>Rev.</label><input id="cab-rev-manual" type="number" step="1" min="0" value="${esc(lista.rev_manual ?? "")}" placeholder="Conferir com a última revisão da lista"></div>
        <div><label>Data de Emissão</label><input id="cab-data-emissao" type="date" value="${paraDataInput(lista.data_emissao_manual)}"></div>
      </div>
      <div class="campo-linha campo-dupla">
        <div><label>Nome do Elaborador</label><input id="cab-elaborador-nome" value="${esc(lista.elaborador_nome || "")}"></div>
        <div><label>Sigla</label><input id="cab-elaborador-sigla" value="${esc(lista.elaborador_sigla || "")}"></div>
      </div>
      <div class="campo-linha campo-dupla">
        <div><label>Nome do Verificador</label><input id="cab-verificador-nome" value="${esc(lista.verificador_nome || "")}"></div>
        <div><label>Sigla</label><input id="cab-verificador-sigla" value="${esc(lista.verificador_sigla || "")}"></div>
      </div>
      <div class="campo-linha campo-dupla">
        <div><label>Nome do Aprovador</label><input id="cab-aprovador-nome" value="${esc(lista.aprovador_nome || "")}"></div>
        <div><label>Sigla</label><input id="cab-aprovador-sigla" value="${esc(lista.aprovador_sigla || "")}"></div>
      </div>
      <div class="campo-linha campo-dupla">
        <div><label>Nome do Autorizado</label><input id="cab-autorizado-nome" value="${esc(lista.autorizado_nome || "")}"></div>
        <div><label>Sigla</label><input id="cab-autorizado-sigla" value="${esc(lista.autorizado_sigla || "")}"></div>
      </div>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario ${somenteDados ? "somente-admin" : ""}" id="btn-continuar-cabecalho">${somenteDados ? "Salvar" : "Continuar"}</button>
    </div>
  `, "modal-media");
  aplicarPermissoes();

  document.getElementById("btn-continuar-cabecalho").addEventListener("click", () => {
    const numero_desenho = document.getElementById("cab-numero-desenho").value.trim();
    if (!numero_desenho) { toast("Informe o número do desenho de referência", "erro"); return; }
    const listaAtualizada = {
      ...lista,
      numero_desenho,
      subtitulo: document.getElementById("cab-subtitulo").value.trim(),
      area_titulo: document.getElementById("cab-area-titulo").value.trim(),
      disciplina: document.getElementById("cab-disciplina").value.trim(),
      titulo: document.getElementById("cab-titulo").value.trim(),
      numero_cliente: document.getElementById("cab-numero-cliente").value.trim(),
      numero_fornecedor: document.getElementById("cab-numero-fornecedor").value.trim(),
      rev_manual: document.getElementById("cab-rev-manual").value.trim(),
      data_emissao_manual: document.getElementById("cab-data-emissao").value,
      elaborador_nome: document.getElementById("cab-elaborador-nome").value.trim(),
      elaborador_sigla: document.getElementById("cab-elaborador-sigla").value.trim(),
      verificador_nome: document.getElementById("cab-verificador-nome").value.trim(),
      verificador_sigla: document.getElementById("cab-verificador-sigla").value.trim(),
      aprovador_nome: document.getElementById("cab-aprovador-nome").value.trim(),
      aprovador_sigla: document.getElementById("cab-aprovador-sigla").value.trim(),
      autorizado_nome: document.getElementById("cab-autorizado-nome").value.trim(),
      autorizado_sigla: document.getElementById("cab-autorizado-sigla").value.trim(),
    };
    if (somenteDados) {
      salvarCabecalhoLista(listaId, listaAtualizada);
    } else {
      renderEditorLista(listaId, listaAtualizada);
    }
  });
}

// TELA 2: busca de materiais + tabela (Material | Quantidade).
function renderEditorLista(listaId, lista) {
  const resumo = [
    lista.numero_desenho,
    `${lista.numero_cliente || "-"} / ${lista.numero_fornecedor || "-"}`,
    lista.titulo,
  ].filter(Boolean).join(" — ");

  abrirModal(`
    <h3>Materiais — ${esc(resumo)}</h3>
    <div class="busca-adicionar-material">
      <div class="busca-input-wrap">
        <input id="busca-novo-material" placeholder="Buscar por código ou descrição..." autocomplete="off">
        <div class="autocomplete-lista oculto" id="autocomplete-lista"></div>
      </div>
      <button class="btn-secundario" id="btn-adicionar-item" type="button">Adicionar</button>
    </div>
    <div class="chips-selecionados" id="chips-selecionados"></div>
    <table class="tabela">
      <thead><tr><th>Material</th><th style="width:110px">Quantidade</th><th></th></tr></thead>
      <tbody id="itens-editor"></tbody>
    </table>
    <div class="modal-acoes">
      ${listaId ? `
        <a class="btn-secundario" href="/api/listas/${listaId}/relatorio/excel" target="_blank">Relatório Excel</a>
      ` : ""}
      <span style="flex:1"></span>
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario somente-admin" id="btn-revisar-desenho">Revisar lista</button>
    </div>
  `, "modal-grande");
  aplicarPermissoes();

  const selecionados = new Map();
  const inputBusca = document.getElementById("busca-novo-material");
  const listaAutocomplete = document.getElementById("autocomplete-lista");
  const btnAdicionar = document.getElementById("btn-adicionar-item");
  const chipsCont = document.getElementById("chips-selecionados");

  function buscarMateriais(termo) {
    const alvo = termo.trim().toLowerCase();
    if (!alvo) {
      return [...state.materiais]
        .sort((a, b) => (a.descricao || "").localeCompare(b.descricao || "", "pt-BR"))
        .slice(0, 100);
    }
    return state.materiais
      .filter((m) => m.codigo.toLowerCase().includes(alvo) || (m.descricao || "").toLowerCase().includes(alvo))
      .map((m) => ({ m, comeca: m.codigo.toLowerCase().startsWith(alvo) || (m.descricao || "").toLowerCase().startsWith(alvo) }))
      .sort((a, b) => {
        if (a.comeca !== b.comeca) return a.comeca ? -1 : 1;
        return (a.m.descricao || "").localeCompare(b.m.descricao || "", "pt-BR");
      })
      .map((x) => x.m)
      .slice(0, 100);
  }

  function fecharAutocomplete() {
    listaAutocomplete.classList.add("oculto");
    listaAutocomplete.innerHTML = "";
  }

  function redesenharChips() {
    const itens = Array.from(selecionados.values());
    chipsCont.innerHTML = itens.map((m) => `
      <span class="chip">${esc(m.codigo)}<button type="button" class="chip-remover" data-material-id="${m.id}" title="Remover da seleção">&times;</button></span>
    `).join("");
    chipsCont.querySelectorAll(".chip-remover").forEach((btn) => {
      btn.addEventListener("click", () => {
        selecionados.delete(Number(btn.dataset.materialId));
        redesenharChips();
      });
    });
    btnAdicionar.textContent = selecionados.size ? `Adicionar (${selecionados.size})` : "Adicionar";
  }

  function atualizarAutocomplete() {
    const resultados = buscarMateriais(inputBusca.value);
    if (!resultados.length) { fecharAutocomplete(); return; }
    listaAutocomplete.innerHTML = resultados.map((m) => `
      <div class="autocomplete-item ${selecionados.has(m.id) ? "selecionado" : ""}" data-material-id="${m.id}">
        <input type="checkbox" tabindex="-1" ${selecionados.has(m.id) ? "checked" : ""}>
        ${_rotuloMaterialHtml(m)}
      </div>
    `).join("");
    listaAutocomplete.classList.remove("oculto");
    listaAutocomplete.querySelectorAll(".autocomplete-item").forEach((el) => {
      el.addEventListener("click", () => {
        const id = Number(el.dataset.materialId);
        const material = resultados.find((m) => m.id === id);
        if (selecionados.has(id)) selecionados.delete(id);
        else selecionados.set(id, material);
        el.classList.toggle("selecionado");
        el.querySelector("input[type=checkbox]").checked = selecionados.has(id);
        redesenharChips();
      });
    });
  }

  inputBusca.addEventListener("input", atualizarAutocomplete);
  inputBusca.addEventListener("focus", atualizarAutocomplete);
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".busca-input-wrap")) fecharAutocomplete();
  });

  btnAdicionar.addEventListener("click", () => {
    if (!selecionados.size) { toast("Selecione ao menos um material na busca", "erro"); return; }
    selecionados.forEach((material) => {
      const existente = window._itensEditor.find((i) => i.material_id === material.id);
      if (existente) {
        existente.quantidade = Number(existente.quantidade || 0) + 1;
      } else {
        window._itensEditor.push({
          material_id: material.id, codigo: material.codigo, descricao: material.descricao,
          fabricante: material.fabricante, bitola: material.bitola, unidade: material.unidade,
          quantidade: 1, observacao: "",
        });
      }
    });
    selecionados.clear();
    inputBusca.value = "";
    fecharAutocomplete();
    redesenharChips();
    redesenharItensEditor();
  });

  document.getElementById("btn-revisar-desenho").addEventListener("click", () => {
    if (!window._itensEditor.length) { toast("Adicione ao menos um material", "erro"); return; }
    window._editorCabecalho = {
      numero_desenho: lista.numero_desenho,
      subtitulo: lista.subtitulo || "",
      area_titulo: lista.area_titulo || "",
      disciplina: lista.disciplina || "",
      titulo: lista.titulo || "",
      numero_cliente: lista.numero_cliente || "",
      numero_fornecedor: lista.numero_fornecedor || "",
      rev_manual: lista.rev_manual ?? "",
      data_emissao_manual: paraDataInput(lista.data_emissao_manual),
      elaborador_nome: lista.elaborador_nome || "",
      elaborador_sigla: lista.elaborador_sigla || "",
      verificador_nome: lista.verificador_nome || "",
      verificador_sigla: lista.verificador_sigla || "",
      aprovador_nome: lista.aprovador_nome || "",
      aprovador_sigla: lista.aprovador_sigla || "",
      autorizado_nome: lista.autorizado_nome || "",
      autorizado_sigla: lista.autorizado_sigla || "",
    };
    renderReviewLista(listaId, lista);
  });

  redesenharItensEditor();

  function redesenharItensEditor() {
    const tbody = document.getElementById("itens-editor");
    tbody.innerHTML = window._itensEditor.map((item, idx) => `
      <tr>
        <td>${_rotuloMaterialHtml(item)}</td>
        <td><input type="number" step="1" min="0" class="item-qtd" data-idx="${idx}" value="${Math.round(Number(item.quantidade)) || 0}" style="width:100px"></td>
        <td><button class="btn-perigo" type="button" data-idx="${idx}">Remover</button></td>
      </tr>`).join("") || `<tr><td colspan="3">Nenhum material adicionado.</td></tr>`;

    tbody.querySelectorAll(".item-qtd").forEach((input) => {
      input.addEventListener("input", (e) => {
        window._itensEditor[Number(input.dataset.idx)].quantidade = e.target.value;
      });
    });
    tbody.querySelectorAll(".btn-perigo").forEach((btn) => {
      btn.addEventListener("click", () => {
        window._itensEditor.splice(Number(btn.dataset.idx), 1);
        redesenharItensEditor();
      });
    });
  }
}

// TE do carimbo padrão de engenharia - só exigido ao emitir (não no rascunho).
const TIPOS_EMISSAO = {
  A: "PRELIMINAR", B: "PARA APROVAÇÃO", C: "PARA CONHECIMENTO", D: "PARA COTAÇÃO",
  E: "PARA CONSTRUÇÃO", F: "CONFORME COMPRADO", G: "CONFORME CONSTRUÍDO", H: "CANCELADO",
};

function renderReviewLista(listaId, lista) {
  const linhas = window._itensEditor.map((item, idx) => `
    <tr>
      <td>${esc(item.codigo)}</td><td>${esc(item.descricao)}</td><td>${esc(item.fabricante || "")}</td><td>${esc(item.bitola || "")}</td>
      <td><input type="number" step="1" min="0" class="revisao-item-qtd" data-idx="${idx}" value="${Math.round(Number(item.quantidade)) || 0}" style="width:90px"></td>
      <td>${esc(item.unidade || "")}</td>
    </tr>`).join("");

  abrirModal(`
    <h3>Revisar Lista por Desenho — ${esc(window._editorCabecalho.numero_desenho)}</h3>
    <div class="campo-linha somente-admin" style="max-width:340px;">
      <label>Tipo de Emissão (TE) — obrigatório para emitir</label>
      <select id="rev-tipo-emissao" style="width:100%">
        <option value="">-- Selecione --</option>
        ${Object.entries(TIPOS_EMISSAO).map(([cod, desc]) => `<option value="${cod}">${cod} - ${desc}</option>`).join("")}
      </select>
    </div>
    <div style="max-height:420px; overflow-y:auto; margin:12px 0;">
      <table class="tabela">
        <thead><tr><th>Código</th><th>Descrição</th><th>Fabricante</th><th>Bitola</th><th>Qtd</th><th>Unidade</th></tr></thead>
        <tbody>${linhas}</tbody>
      </table>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-secundario" id="btn-voltar-editor-desenho">Voltar</button>
      <button class="btn-secundario somente-admin" id="btn-salvar-rascunho-desenho">Salvar rascunho</button>
      <button class="btn-primario somente-admin" id="btn-emitir-desenho">Emitir versão</button>
    </div>
  `, "modal-grande");
  aplicarPermissoes();

  document.querySelectorAll(".revisao-item-qtd").forEach((input) => {
    input.addEventListener("input", (e) => {
      window._itensEditor[Number(input.dataset.idx)].quantidade = Math.round(Number(e.target.value)) || 0;
    });
  });
  document.getElementById("btn-voltar-editor-desenho").addEventListener("click", () => renderEditorLista(listaId, { ...lista, ...window._editorCabecalho }));
  document.getElementById("btn-salvar-rascunho-desenho").addEventListener("click", () => salvarEditorLista(listaId, "rascunho"));
  document.getElementById("btn-emitir-desenho").addEventListener("click", () => {
    const tipoEmissao = document.getElementById("rev-tipo-emissao").value;
    if (!tipoEmissao) { toast("Selecione o tipo de emissão (TE) para emitir a versão", "erro"); return; }
    salvarEditorLista(listaId, "salvo", tipoEmissao);
  });
}

async function salvarEditorLista(listaId, status, tipoEmissao) {
  const itens = (window._itensEditor || []).filter((i) => i.material_id);
  const cabecalho = window._editorCabecalho || {};
  const payload = {
    numero_desenho: cabecalho.numero_desenho,
    subtitulo: cabecalho.subtitulo,
    area_titulo: cabecalho.area_titulo,
    disciplina: cabecalho.disciplina,
    titulo: cabecalho.titulo,
    numero_cliente: cabecalho.numero_cliente,
    numero_fornecedor: cabecalho.numero_fornecedor,
    rev_manual: cabecalho.rev_manual,
    data_emissao_manual: cabecalho.data_emissao_manual,
    elaborador_nome: cabecalho.elaborador_nome,
    elaborador_sigla: cabecalho.elaborador_sigla,
    verificador_nome: cabecalho.verificador_nome,
    verificador_sigla: cabecalho.verificador_sigla,
    aprovador_nome: cabecalho.aprovador_nome,
    aprovador_sigla: cabecalho.aprovador_sigla,
    autorizado_nome: cabecalho.autorizado_nome,
    autorizado_sigla: cabecalho.autorizado_sigla,
    status,
    tipo_emissao: tipoEmissao,
    itens: itens.map((i) => ({ material_id: Number(i.material_id), quantidade: Math.round(Number(i.quantidade)) || 0, observacao: i.observacao || "" })),
  };
  const mensagem = status === "rascunho" ? "Rascunho salvo" : "Versão emitida com sucesso";
  try {
    if (listaId) {
      await api(`/api/listas/${listaId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api(`/api/projetos/${state.projetoAtual.id}/listas`, { method: "POST", body: JSON.stringify(payload) });
    }
    toast(mensagem);
    fecharModal();
    carregarListas(state.projetoAtual.id);
  } catch (err) { toast(err.message, "erro"); }
}

async function verVersao(listaId, versaoId) {
  const dados = await api(`/api/versoes/${versaoId}`);
  const lista = dados.lista || {};
  const assinaturas = [
    lista.elaborador_nome ? `Elaborado por: ${esc(lista.elaborador_nome)}${lista.elaborador_sigla ? ` (${esc(lista.elaborador_sigla)})` : ""}` : "",
    lista.verificador_nome ? `Verificado por: ${esc(lista.verificador_nome)}${lista.verificador_sigla ? ` (${esc(lista.verificador_sigla)})` : ""}` : "",
    lista.aprovador_nome ? `Aprovado por: ${esc(lista.aprovador_nome)}${lista.aprovador_sigla ? ` (${esc(lista.aprovador_sigla)})` : ""}` : "",
  ].filter(Boolean).join(" &nbsp;|&nbsp; ");
  abrirModal(`
    <h3>Lista por Desenho — ${esc(lista.numero_desenho || "-")} (Versão ${dados.versao.versao})${dados.versao.status === "rascunho" ? '<span class="badge-rascunho">Rascunho</span>' : ""}</h3>
    <div class="info-versao">
      Título: <b>${esc(lista.titulo || "-")}</b> &nbsp;|&nbsp; Nº Cliente: <b>${esc(lista.numero_cliente || "-")}</b> &nbsp;|&nbsp; Nº Fornecedor: <b>${esc(lista.numero_fornecedor || "-")}</b><br>
      ${assinaturas ? assinaturas + "<br>" : ""}
      Salva em ${new Date(dados.versao.criado_em).toLocaleString("pt-BR")} por <b>${esc(dados.versao.criado_por_nome || "-")}</b>
    </div>
    <table class="tabela">
      <thead><tr><th>Código</th><th>Descrição</th><th>Qtd</th><th>Unidade</th></tr></thead>
      <tbody>
        ${dados.itens.map((i) => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.descricao)}</td><td>${formatarQuantidade(i.quantidade, i.unidade)}</td><td>${esc(i.unidade)}</td></tr>`).join("") || "<tr><td colspan='4'>Sem itens</td></tr>"}
      </tbody>
    </table>
    <div class="modal-acoes">
      <a class="btn-secundario" href="/api/listas/${listaId}/relatorio/excel?versao_id=${versaoId}" target="_blank">Relatório Excel</a>
      <span style="flex:1"></span>
      ${dados.versao.status === "rascunho" ? `<button class="btn-primario somente-admin" id="btn-editar-rascunho-desenho">Editar rascunho</button>` : ""}
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Fechar</button>
    </div>
  `, "modal-grande");
  aplicarPermissoes();

  if (dados.versao.status === "rascunho") {
    document.getElementById("btn-editar-rascunho-desenho").addEventListener("click", () => abrirEditorMateriais(listaId));
  }
}

const CAMPOS_QUANTIDADE = ["quantidade", "quantidade_base", "quantidade_atualizada"];
function mostrarItensVersaoGenerico(titulo, itens, campos, rotulos) {
  abrirModal(`
    <h3>${titulo}</h3>
    <table class="tabela">
      <thead><tr>${rotulos.map((r) => `<th>${r}</th>`).join("")}</tr></thead>
      <tbody>
        ${itens.map((i) => `<tr>${campos.map((c) => `<td>${CAMPOS_QUANTIDADE.includes(c) ? formatarQuantidade(i[c], i.unidade) : esc(i[c])}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${rotulos.length}">Sem itens</td></tr>`}
      </tbody>
    </table>
    <div class="modal-acoes"><button class="btn-secundario" onclick="fecharModalComConfirmacao()">Fechar</button></div>
  `, "modal-grande");
}

// Formata quantidade de acordo com a unidade: unidades de contagem (pç, un,
// cj...) mostram numero inteiro; medidas (m, m2, etc.) mostram 2 casas decimais.
function formatarQuantidade(valor, unidade) {
  const numero = Number(valor) || 0;
  return Math.round(numero).toLocaleString("pt-BR");
}

// ---------- ÁRVORE DE VERSÕES (compartilhado entre Lista PQ e Lista de Compras) ----------
// PQ e Compras têm shape de dados diferente (origens em lista plana vs. PQ→origens
// aninhado), então só a mecânica de expandir/renderizar o container é compartilhada;
// a montagem de cada nó (renderNoPQ/renderNoCompras) continua separada.
function _renderArvore(containerId, mensagemVazia, versoes, estado, renderNoFn) {
  estado.versoes = versoes;
  const cont = document.getElementById(containerId);
  cont.innerHTML = versoes.length
    ? versoes.map(renderNoFn).join("")
    : `<div class="arvore-vazio">${mensagemVazia}</div>`;
}

function _toggleArvore(estado, versaoId, renderArvoreFn) {
  if (estado.expandidas.has(versaoId)) estado.expandidas.delete(versaoId);
  else estado.expandidas.add(versaoId);
  renderArvoreFn(estado.versoes);
}

// ---------- LISTA PQ ----------
const pqArvoreState = { versoes: [], expandidas: new Set() };

async function carregarListaPQ() {
  const [versoes, rascunho] = await Promise.all([
    api(`/api/projetos/${state.projetoAtual.id}/lista-pq/versoes`),
    api(`/api/projetos/${state.projetoAtual.id}/lista-pq/rascunho`),
  ]);
  renderArvorePQ(versoes);
  window._pqRascunho = rascunho.versao ? rascunho : null;
  document.getElementById("btn-continuar-rascunho-pq").classList.toggle("oculto", !window._pqRascunho);
}

function renderArvorePQ(versoes) {
  _renderArvore("arvore-pq", "Nenhuma versão da Planilha de Quantidades salva ainda.", versoes, pqArvoreState, renderNoPQ);
}

function renderNoPQ(v) {
  const aberta = pqArvoreState.expandidas.has(v.id);
  const origens = v.origens || [];
  const filhosHtml = origens.length
    ? origens.map((o) => `
        <div class="arvore-linha arvore-linha-versao">
          <span class="arvore-toggle invisivel"></span>
          ${ICONE_ARQUIVO}
          <span class="arvore-label">
            <span class="arvore-titulo">${esc(o.numero_desenho)}${o.titulo ? " — " + esc(o.titulo) : ""}</span>
            <span class="arvore-sub">v${o.versao_numero}</span>
          </span>
        </div>`).join("")
    : `<div class="arvore-carregando">Nenhum desenho de origem registrado.</div>`;
  return `
    <div class="arvore-no">
      <div class="arvore-linha arvore-linha-pasta">
        <button class="arvore-toggle ${aberta ? "aberto" : ""}" onclick="toggleArvorePQ(${v.id})" aria-label="Expandir">${ICONE_SETA}</button>
        ${ICONE_PASTA}
        <span class="arvore-label" onclick="toggleArvorePQ(${v.id})">
          <span class="arvore-titulo">v${v.versao}${v.status === "rascunho" ? '<span class="badge-rascunho">Rascunho</span>' : ""}</span>
          <span class="arvore-sub">${new Date(v.criado_em).toLocaleString("pt-BR")} · ${esc(v.criado_por_nome || "-")}</span>
        </span>
        <span class="arvore-acoes">
          <button class="link-acao" onclick="verVersaoPQ(${v.id})">Ver</button>
        </span>
      </div>
      <div class="arvore-filhos ${aberta ? "" : "oculto"}">${aberta ? filhosHtml : ""}</div>
    </div>`;
}

function toggleArvorePQ(versaoId) {
  _toggleArvore(pqArvoreState, versaoId, renderArvorePQ);
}

async function verVersaoPQ(versaoId) {
  const dados = await api(`/api/lista-pq/versoes/${versaoId}`);
  mostrarItensVersaoGenerico(
    `Planilha de Quantidades — versão ${dados.versao.versao}${dados.versao.status === "rascunho" ? '<span class="badge-rascunho">Rascunho</span>' : ""}`, dados.itens,
    ["codigo", "descricao", "fabricante", "bitola", "quantidade_base", "percentual", "quantidade_atualizada", "unidade"],
    ["Código", "Descrição", "Fabricante", "Bitola", "Qtd. Base", "%", "Qtd. Atualizada", "Unidade"],
  );
}

function calcularQtdAtualizada(item) {
  return item.quantidade_base * (1 + item.percentual / 100);
}

document.getElementById("btn-revisar-pq").addEventListener("click", async () => {
  const projetoId = state.projetoAtual.id;
  const listaIds = window._pqListaIdsSelecionados || [];
  const [base, atual] = await Promise.all([
    api(`/api/projetos/${projetoId}/lista-pq/base`, { method: "POST", body: JSON.stringify({ lista_ids: listaIds }) }),
    api(`/api/projetos/${projetoId}/lista-pq`),
  ]);
  if (!base.length) { toast("Nenhum material encontrado nas Listas por Desenho deste projeto ainda", "erro"); return; }
  const percentuaisAtuais = {};
  (atual.itens || []).forEach((i) => { percentuaisAtuais[i.material_id] = Number(i.percentual); });

  window._pqDraft = base.map((b) => ({
    material_id: b.material_id, codigo: b.codigo, descricao: b.descricao, fabricante: b.fabricante,
    bitola: b.bitola, unidade: b.unidade, quantidade_base: Number(b.quantidade_base),
    percentual: percentuaisAtuais[b.material_id] || 0, observacao: "",
  }));
  renderModalRevisaoPQ();
});

// Retoma um rascunho da Lista PQ já em aberto, com os itens/percentuais
// exatamente como estavam no último "Salvar rascunho" - pula a seleção de
// listas e o recálculo da base, que já foram feitos antes da pausa.
document.getElementById("btn-continuar-rascunho-pq").addEventListener("click", () => {
  const r = window._pqRascunho;
  if (!r) return;
  window._pqListaIdsSelecionados = (r.origens || []).map((o) => o.lista_desenho_id);
  window._pqDraft = r.itens.map((i) => ({
    material_id: i.material_id, codigo: i.codigo, descricao: i.descricao, fabricante: i.fabricante,
    bitola: i.bitola, unidade: i.unidade, quantidade_base: Number(i.quantidade_base),
    percentual: Number(i.percentual), observacao: i.observacao || "",
  }));
  renderModalRevisaoPQ();
});

function renderModalRevisaoPQ() {
  const linhas = window._pqDraft.map((item, idx) => `
    <tr>
      <td>${esc(item.codigo)}</td>
      <td>${esc(item.descricao)}</td>
      <td>${esc(item.fabricante || "")}</td>
      <td>${esc(item.bitola || "")}</td>
      <td style="text-align:right">${formatarQuantidade(item.quantidade_base, item.unidade)}</td>
      <td><input type="number" step="0.01" class="pq-percentual" data-idx="${idx}" value="${item.percentual}" style="width:80px"></td>
      <td class="pq-qtd-atualizada" data-idx="${idx}" style="text-align:right">${formatarQuantidade(calcularQtdAtualizada(item), item.unidade)}</td>
      <td>${esc(item.unidade)}</td>
    </tr>`).join("");

  abrirModal(`
    <h3>Revisar Planilha de Quantidades</h3>
    <div class="form-grid" style="flex-direction:row; align-items:flex-end; gap:10px;">
      <div style="flex:1">
        <label>Aplicar percentual a todos os itens</label>
        <input type="number" step="0.01" id="pq-percentual-massa" placeholder="Ex: 10">
      </div>
      <button type="button" class="btn-secundario" id="btn-aplicar-percentual-massa">Aplicar a todos</button>
    </div>
    <div style="max-height:360px; overflow-y:auto; margin:12px 0;">
      <table class="tabela">
        <thead><tr><th>Código</th><th>Descrição</th><th>Fabricante</th><th>Bitola</th><th>Qtd. Base</th><th>%</th><th>Qtd. Atualizada</th><th>Unidade</th></tr></thead>
        <tbody>${linhas}</tbody>
      </table>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-secundario" id="btn-salvar-rascunho-pq">Salvar rascunho</button>
      <button class="btn-primario" id="btn-emitir-pq">Emitir versão</button>
    </div>
  `, "modal-grande");

  document.querySelectorAll(".pq-percentual").forEach((input) => {
    input.addEventListener("input", () => {
      const idx = Number(input.dataset.idx);
      window._pqDraft[idx].percentual = Number(input.value) || 0;
      document.querySelector(`.pq-qtd-atualizada[data-idx="${idx}"]`).textContent =
        formatarQuantidade(calcularQtdAtualizada(window._pqDraft[idx]), window._pqDraft[idx].unidade);
    });
  });
  document.getElementById("btn-aplicar-percentual-massa").addEventListener("click", () => {
    const valor = Number(document.getElementById("pq-percentual-massa").value) || 0;
    window._pqDraft.forEach((item) => { item.percentual = valor; });
    renderModalRevisaoPQ();
  });
  document.getElementById("btn-salvar-rascunho-pq").addEventListener("click", () => salvarVersaoPQ("rascunho"));
  document.getElementById("btn-emitir-pq").addEventListener("click", () => salvarVersaoPQ("salvo"));
}

async function salvarVersaoPQ(status) {
  const itens = window._pqDraft.map((item) => ({
    material_id: item.material_id, quantidade_base: item.quantidade_base, percentual: item.percentual,
    quantidade_atualizada: calcularQtdAtualizada(item), observacao: item.observacao || "",
  }));
  try {
    const lista_ids = window._pqListaIdsSelecionados || [];
    await api(`/api/projetos/${state.projetoAtual.id}/lista-pq`, { method: "POST", body: JSON.stringify({ itens, lista_ids, status }) });
    fecharModal();
    toast(status === "rascunho" ? "Rascunho da Planilha de Quantidades salvo" : "Nova versão da Planilha de Quantidades emitida com sucesso");
    document.getElementById("btn-revisar-pq").classList.add("oculto");
    document.getElementById("btn-criar-pq").classList.remove("oculto");
    carregarListaPQ();
  } catch (err) { toast(err.message, "erro"); }
}

// ---------- LISTA DE COMPRAS ----------
const comprasArvoreState = { versoes: [], expandidas: new Set() };

async function carregarListaCompras() {
  const [versoes, rascunho] = await Promise.all([
    api(`/api/projetos/${state.projetoAtual.id}/lista-compras/versoes`),
    api(`/api/projetos/${state.projetoAtual.id}/lista-compras/rascunho`),
  ]);
  renderArvoreCompras(versoes);
  window._comprasRascunho = rascunho.versao ? rascunho : null;
  document.getElementById("btn-continuar-rascunho-compras").classList.toggle("oculto", !window._comprasRascunho);
}

function renderArvoreCompras(versoes) {
  _renderArvore("arvore-compras", "Nenhuma versão da Lista de Compras salva ainda.", versoes, comprasArvoreState, renderNoCompras);
}

function renderNoCompras(v) {
  const aberta = comprasArvoreState.expandidas.has(v.id);
  const pq = v.origem_pq;
  const filhosHtml = pq
    ? `
        <div class="arvore-linha arvore-linha-versao">
          <span class="arvore-toggle invisivel"></span>
          ${ICONE_ARQUIVO}
          <span class="arvore-label">
            <span class="arvore-titulo">Planilha de Quantidades v${pq.versao}</span>
            <span class="arvore-sub">${new Date(pq.criado_em).toLocaleString("pt-BR")}</span>
          </span>
        </div>
        ${(pq.origens || []).map((o) => `
          <div class="arvore-linha arvore-linha-versao" style="margin-left:28px">
            <span class="arvore-toggle invisivel"></span>
            ${ICONE_ARQUIVO}
            <span class="arvore-label">
              <span class="arvore-titulo">${esc(o.numero_desenho)}${o.titulo ? " — " + esc(o.titulo) : ""}</span>
              <span class="arvore-sub">v${o.versao_numero}</span>
            </span>
          </div>`).join("")}`
    : `<div class="arvore-carregando">Origem da Planilha de Quantidades não registrada.</div>`;
  return `
    <div class="arvore-no">
      <div class="arvore-linha arvore-linha-pasta">
        <button class="arvore-toggle ${aberta ? "aberto" : ""}" onclick="toggleArvoreCompras(${v.id})" aria-label="Expandir">${ICONE_SETA}</button>
        ${ICONE_PASTA}
        <span class="arvore-label" onclick="toggleArvoreCompras(${v.id})">
          <span class="arvore-titulo">v${v.versao}${v.status === "rascunho" ? '<span class="badge-rascunho">Rascunho</span>' : ""}</span>
          <span class="arvore-sub">${new Date(v.criado_em).toLocaleString("pt-BR")} · ${esc(v.criado_por_nome || "-")}</span>
        </span>
        <span class="arvore-acoes">
          <button class="link-acao" onclick="verVersaoCompras(${v.id})">Ver</button>
        </span>
      </div>
      <div class="arvore-filhos ${aberta ? "" : "oculto"}">${aberta ? filhosHtml : ""}</div>
    </div>`;
}

function toggleArvoreCompras(versaoId) {
  _toggleArvore(comprasArvoreState, versaoId, renderArvoreCompras);
}

async function verVersaoCompras(versaoId) {
  const dados = await api(`/api/lista-compras/versoes/${versaoId}`);
  mostrarItensVersaoGenerico(
    `Lista de Compras — versão ${dados.versao.versao}${dados.versao.status === "rascunho" ? '<span class="badge-rascunho">Rascunho</span>' : ""}`, dados.itens,
    ["codigo", "descricao", "fabricante", "bitola", "quantidade", "unidade"],
    ["Código", "Descrição", "Fabricante", "Bitola", "Quantidade", "Unidade"],
  );
}

document.getElementById("btn-revisar-compras").addEventListener("click", async () => {
  const listaIds = window._comprasListaIdsSelecionados || [];
  const base = await api(`/api/projetos/${state.projetoAtual.id}/lista-compras/base`, {
    method: "POST", body: JSON.stringify({ lista_ids: listaIds }),
  });
  if (!base.length) { toast("Nenhum material encontrado para as listas selecionadas", "erro"); return; }
  window._comprasDraft = base.map((b) => ({
    material_id: b.material_id, codigo: b.codigo, descricao: b.descricao, fabricante: b.fabricante,
    bitola: b.bitola, unidade: b.unidade, quantidade: Number(b.quantidade), observacao: "",
  }));
  renderModalRevisaoCompras();
});

// Retoma um rascunho da Lista de Compras já em aberto, com as quantidades
// exatamente como estavam no último "Salvar rascunho".
document.getElementById("btn-continuar-rascunho-compras").addEventListener("click", () => {
  const r = window._comprasRascunho;
  if (!r) return;
  window._comprasDraft = r.itens.map((i) => ({
    material_id: i.material_id, codigo: i.codigo, descricao: i.descricao, fabricante: i.fabricante,
    bitola: i.bitola, unidade: i.unidade, quantidade: Number(i.quantidade), observacao: i.observacao || "",
  }));
  renderModalRevisaoCompras();
});

function renderModalRevisaoCompras() {
  const linhas = window._comprasDraft.map((item, idx) => `
    <tr>
      <td>${esc(item.codigo)}</td>
      <td>${esc(item.descricao)}</td>
      <td><input type="number" step="1" min="0" class="compras-qtd" data-idx="${idx}" value="${Math.round(Number(item.quantidade)) || 0}" style="width:100px"></td>
      <td>${esc(item.unidade)}</td>
    </tr>`).join("");

  abrirModal(`
    <h3>Revisar Lista de Compras</h3>
    <p style="color:var(--cinza); font-size:13px;">Itens vindos da última versão salva da Planilha de Quantidades. Ajuste as quantidades se necessário.</p>
    <div style="max-height:360px; overflow-y:auto; margin:12px 0;">
      <table class="tabela">
        <thead><tr><th>Código</th><th>Descrição</th><th>Quantidade</th><th>Unidade</th></tr></thead>
        <tbody>${linhas}</tbody>
      </table>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-secundario" id="btn-salvar-rascunho-compras">Salvar rascunho</button>
      <button class="btn-primario" id="btn-emitir-compras">Emitir versão</button>
    </div>
  `, "modal-grande");

  document.querySelectorAll(".compras-qtd").forEach((input) => {
    input.addEventListener("input", () => {
      window._comprasDraft[Number(input.dataset.idx)].quantidade = Math.round(Number(input.value)) || 0;
    });
  });
  document.getElementById("btn-salvar-rascunho-compras").addEventListener("click", () => salvarVersaoCompras("rascunho"));
  document.getElementById("btn-emitir-compras").addEventListener("click", () => salvarVersaoCompras("salvo"));
}

async function salvarVersaoCompras(status) {
  const itens = window._comprasDraft.map((item) => ({
    material_id: item.material_id, quantidade: Math.round(Number(item.quantidade)) || 0, observacao: item.observacao || "",
  }));
  try {
    await api(`/api/projetos/${state.projetoAtual.id}/lista-compras`, { method: "POST", body: JSON.stringify({ itens, status }) });
    fecharModal();
    toast(status === "rascunho" ? "Rascunho da Lista de Compras salvo" : "Nova versão da Lista de Compras emitida com sucesso");
    document.getElementById("btn-revisar-compras").classList.add("oculto");
    document.getElementById("btn-criar-compras").classList.remove("oculto");
    carregarListaCompras();
  } catch (err) { toast(err.message, "erro"); }
}

// ---------- USUÁRIOS ----------
async function carregarUsuarios() {
  const usuarios = await api("/api/usuarios");
  const tbody = document.getElementById("tbody-usuarios");
  tbody.innerHTML = usuarios.map((u) => `
    <tr>
      <td>${esc(u.nome)}</td><td>${esc(u.email)}</td><td>${esc(u.perfil)}</td><td>${u.ativo ? "Sim" : "Não"}</td>
      <td>${u.sessao_ativa ? '<span class="badge-rascunho" style="background:#eaf1fb;color:var(--azul);">Ativa</span>' : "-"}</td>
      <td class="acoes-linha">
        <button class="link-acao" onclick='editarUsuario(${esc(JSON.stringify(u))})'>Editar</button>
        ${u.sessao_ativa ? `<button class="link-acao somente-master" onclick="encerrarSessaoUsuario(${u.id}, '${esc(u.nome)}')">Encerrar sessão</button>` : ""}
        ${u.ativo
          ? `<button class="link-acao" onclick="excluirUsuario(${u.id})">Desativar</button>`
          : `<button class="link-acao" onclick='ativarUsuario(${esc(JSON.stringify(u))})'>Ativar</button>`}
      </td>
    </tr>`).join("");
  aplicarPermissoes();
}

async function encerrarSessaoUsuario(id, nome) {
  if (!(await confirmarPersonalizado(`Encerrar a sessão ativa de ${nome}? A pessoa será desconectada e poderá entrar de novo imediatamente.`))) return;
  await api(`/api/usuarios/${id}/encerrar-sessao`, { method: "POST" });
  toast("Sessão encerrada");
  carregarUsuarios();
}

async function ativarUsuario(u) {
  const areas = (u.areas || []).map((a) => a.id);
  try {
    await api(`/api/usuarios/${u.id}`, { method: "PUT", body: JSON.stringify({ nome: u.nome, perfil: u.perfil, ativo: 1, areas }) });
    toast("Usuário reativado");
    carregarUsuarios();
  } catch (err) { toast(err.message, "erro"); }
}

async function modalUsuario(usuario = null) {
  await garantirAreasCarregadas();
  const u = usuario || { nome: "", email: "", perfil: "visualizador", ativo: 1, areas: [] };
  const areasDoUsuario = new Set((u.areas || []).map((a) => a.id));
  const opcoesAreas = state.areas.map((a) => `
    <label style="display:flex; align-items:center; gap:6px; font-weight:normal; margin:2px 0;">
      <input type="checkbox" class="usr-area" value="${a.id}" ${areasDoUsuario.has(a.id) ? "checked" : ""}> ${esc(a.nome)}
    </label>`).join("");

  abrirModal(`
    <h3>${usuario ? "Editar" : "Novo"} Usuário</h3>
    <div class="form-grid">
      <label>Nome</label><input id="usr-nome" value="${esc(u.nome)}">
      <label>Email</label><input id="usr-email" value="${esc(u.email)}" ${usuario ? "disabled" : ""}>
      <label>Perfil</label>
      <select id="usr-perfil">
        ${["master", "administrador", "visualizador"].map((p) => `<option value="${p}" ${u.perfil === p ? "selected" : ""}>${p}</option>`).join("")}
      </select>
      <label>Senha ${usuario ? "(deixe em branco para não alterar)" : ""}</label>
      ${campoSenhaHtml("usr-senha")}
      <div id="usr-areas-wrap" class="${u.perfil === "master" ? "oculto" : ""}">
        <label>Áreas autorizadas</label>
        <div style="border:1px solid var(--borda); border-radius:8px; padding:8px 12px; max-height:160px; overflow-y:auto;">
          ${opcoesAreas || "<span style='color:var(--cinza); font-size:13px;'>Nenhuma área cadastrada ainda.</span>"}
        </div>
      </div>
      ${usuario ? `
        <label style="display:flex; align-items:center; gap:6px; font-weight:normal;">
          <input type="checkbox" id="usr-ativo" ${u.ativo ? "checked" : ""}> Usuário ativo (desmarque para desativar, marque para reativar)
        </label>
      ` : ""}
    </div>
    <div class="modal-acoes">
      ${usuario && usuario.id !== state.usuario.id ? `
        <button class="btn-perigo somente-master" style="margin-right:auto;" onclick="excluirUsuarioPermanente(${usuario.id}, '${esc(usuario.nome)}')">Excluir permanentemente</button>
      ` : ""}
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario" onclick="salvarUsuario(${usuario ? usuario.id : "null"})">Salvar</button>
    </div>
  `);
  aplicarPermissoes();

  document.getElementById("usr-perfil").addEventListener("change", (e) => {
    document.getElementById("usr-areas-wrap").classList.toggle("oculto", e.target.value === "master");
  });
}

async function excluirUsuarioPermanente(id, nome) {
  if (!(await confirmarPersonalizado(
    `Excluir PERMANENTEMENTE o usuário ${nome}? Diferente de "Desativar", isso não pode ser desfeito - o cadastro de login será removido de vez. Projetos e listas criados por essa pessoa continuam existindo normalmente.`
  ))) return;
  try {
    await api(`/api/usuarios/${id}/permanente`, { method: "DELETE" });
    fecharModal();
    toast("Usuário excluído permanentemente");
    carregarUsuarios();
  } catch (err) { toast(err.message, "erro"); }
}

async function salvarUsuario(id) {
  const senha = document.getElementById("usr-senha").value;
  const areas = [...document.querySelectorAll(".usr-area:checked")].map((c) => Number(c.value));
  try {
    if (id) {
      const payload = {
        nome: document.getElementById("usr-nome").value.trim(), perfil: document.getElementById("usr-perfil").value,
        ativo: document.getElementById("usr-ativo").checked ? 1 : 0, areas,
      };
      if (senha) payload.senha = senha;
      await api(`/api/usuarios/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      const payload = {
        nome: document.getElementById("usr-nome").value.trim(),
        email: document.getElementById("usr-email").value.trim(),
        perfil: document.getElementById("usr-perfil").value,
        senha, areas,
      };
      await api("/api/usuarios", { method: "POST", body: JSON.stringify(payload) });
    }
    fecharModal();
    toast("Usuário salvo com sucesso");
    carregarUsuarios();
  } catch (err) { toast(err.message, "erro"); }
}

function editarUsuario(u) { modalUsuario(u); }

async function excluirUsuario(id) {
  if (!(await confirmarPersonalizado("Desativar este usuário?"))) return;
  try {
    await api(`/api/usuarios/${id}`, { method: "DELETE" });
    toast("Usuário desativado");
    carregarUsuarios();
  } catch (err) { toast(err.message, "erro"); }
}

document.getElementById("btn-novo-usuario").addEventListener("click", () => modalUsuario());

// ---------- CONFIGURAÇÕES ----------
async function carregarConfiguracoes() {
  const configs = await api("/api/configuracoes");
  configs.forEach((c) => {
    const el = document.getElementById(`cfg-${c.chave}`);
    if (el) el.value = c.valor || "";
  });
  atualizarPreviewLogoEmpresa();
}

function atualizarPreviewLogoEmpresa() {
  const url = document.getElementById("cfg-logo_url").value.trim();
  const img = document.getElementById("cfg-logo-preview");
  if (url) {
    img.src = url;
    img.classList.remove("oculto");
  } else {
    img.classList.add("oculto");
  }
}

document.getElementById("cfg-logo_url").addEventListener("input", atualizarPreviewLogoEmpresa);

document.getElementById("form-configuracoes").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    nome_empresa: document.getElementById("cfg-nome_empresa").value,
    logo_url: document.getElementById("cfg-logo_url").value,
    formato_data: document.getElementById("cfg-formato_data").value,
  };
  try {
    await api("/api/configuracoes", { method: "PUT", body: JSON.stringify(payload) });
    toast("Configurações salvas");
  } catch (err) { toast(err.message, "erro"); }
});

// ---------- ZONA DE RISCO ----------
function confirmarAcaoRisco(titulo, mensagem, palavra, aoConfirmar) {
  abrirModal(`
    <h3>${titulo}</h3>
    <p style="color:var(--cinza);">${mensagem}</p>
    <p>Para confirmar, digite <b>${palavra}</b> no campo abaixo:</p>
    <input type="text" id="risco-confirmacao-texto" autocomplete="off">
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-perigo" id="btn-confirmar-risco" disabled>${titulo}</button>
    </div>
  `);
  const input = document.getElementById("risco-confirmacao-texto");
  const botao = document.getElementById("btn-confirmar-risco");
  input.addEventListener("input", () => {
    botao.disabled = input.value.trim().toUpperCase() !== palavra;
  });
  botao.addEventListener("click", async () => {
    try {
      const resultado = await aoConfirmar();
      fecharModal();
      toast(`${resultado.excluidos} registro(s) removido(s) com sucesso`);
    } catch (err) { toast(err.message, "erro"); }
  });
}

document.getElementById("btn-risco-materiais").addEventListener("click", () => {
  confirmarAcaoRisco(
    "Excluir todos os materiais",
    "Todos os materiais cadastrados no catálogo serão removidos. Essa ação não pode ser desfeita.",
    "EXCLUIR",
    () => api("/api/risco/materiais", { method: "DELETE" }),
  );
});

document.getElementById("btn-risco-projetos").addEventListener("click", () => {
  confirmarAcaoRisco(
    "Excluir todos os projetos",
    "Todos os projetos, listas por desenho, Planilhas de Quantidades e Listas de Compras serão removidos. Essa ação não pode ser desfeita.",
    "EXCLUIR",
    () => api("/api/risco/projetos", { method: "DELETE" }),
  );
});

document.getElementById("btn-risco-auditoria").addEventListener("click", () => {
  confirmarAcaoRisco(
    "Zerar log de auditoria",
    "Todo o histórico de ações do sistema será apagado permanentemente.",
    "ZERAR",
    () => api("/api/risco/auditoria", { method: "DELETE" }),
  );
});

// ---------- ÁREAS ----------
async function carregarAreas() {
  state.areas = await api("/api/areas");
  const tbody = document.getElementById("tbody-areas");
  tbody.innerHTML = state.areas.map((a) => `
    <tr>
      <td>${esc(a.nome)}</td>
      <td>${a.total_materiais}</td>
      <td class="acoes-linha">
        <button class="link-acao" onclick='modalArea(${JSON.stringify(a)})'>Editar</button>
        <button class="link-acao" onclick="excluirArea(${a.id})">Excluir</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="3">Nenhuma área cadastrada.</td></tr>`;
}

function modalArea(area = null) {
  abrirModal(`
    <h3>${area ? "Editar" : "Nova"} Área</h3>
    <div class="form-grid">
      <label>Nome</label><input id="area-nome" value="${area ? area.nome : ""}">
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModalComConfirmacao()">Cancelar</button>
      <button class="btn-primario" onclick="salvarArea(${area ? area.id : "null"})">Salvar</button>
    </div>
  `);
}

async function salvarArea(id) {
  const nome = document.getElementById("area-nome").value.trim();
  if (!nome) { toast("Informe o nome da área", "erro"); return; }
  try {
    if (id) await api(`/api/areas/${id}`, { method: "PUT", body: JSON.stringify({ nome }) });
    else await api("/api/areas", { method: "POST", body: JSON.stringify({ nome }) });
    fecharModal();
    toast("Área salva com sucesso");
    carregarAreas();
  } catch (err) { toast(err.message, "erro"); }
}

async function excluirArea(id) {
  if (!(await confirmarPersonalizado("Excluir esta área?"))) return;
  try {
    await api(`/api/areas/${id}`, { method: "DELETE" });
    toast("Área excluída");
    carregarAreas();
  } catch (err) { toast(err.message, "erro"); }
}

document.getElementById("btn-nova-area").addEventListener("click", () => modalArea());

// ---------- AUDITORIA ----------
const ROTULOS_ENTIDADE = {
  material: "Materiais", cliente: "Clientes", projeto: "Projetos",
  lista_desenho: "Listas por Desenho", usuario: "Usuários", configuracao: "Configurações",
};
const ROTULOS_ACAO = {
  criar: "Criou", editar: "Editou", excluir: "Excluiu", importar: "Importou", login: "Login", logout: "Logout",
};

const auditoriaState = { offset: 0, limite: 50, entidadesCarregadas: false };

async function carregarAuditoria(reiniciar = false) {
  if (!auditoriaState.entidadesCarregadas) {
    const entidades = await api("/api/auditoria/entidades");
    const select = document.getElementById("auditoria-entidade");
    entidades.forEach((ent) => {
      const opt = document.createElement("option");
      opt.value = ent;
      opt.textContent = ROTULOS_ENTIDADE[ent] || ent;
      select.appendChild(opt);
    });
    auditoriaState.entidadesCarregadas = true;
  }

  if (reiniciar) auditoriaState.offset = 0;

  const params = new URLSearchParams({
    limite: auditoriaState.limite,
    offset: auditoriaState.offset,
  });
  const entidade = document.getElementById("auditoria-entidade").value;
  const busca = document.getElementById("auditoria-busca").value.trim();
  if (entidade) params.set("entidade", entidade);
  if (busca) params.set("q", busca);

  const resultado = await api(`/api/auditoria?${params}`);
  const tbody = document.getElementById("tbody-auditoria");
  const linhas = resultado.itens.map((ev) => `
    <tr>
      <td>${new Date(ev.criado_em).toLocaleString("pt-BR")}</td>
      <td>${esc(ev.usuario_nome)}</td>
      <td><span class="badge-acao ${esc(ev.acao)}">${esc(ROTULOS_ACAO[ev.acao] || ev.acao)}</span></td>
      <td>${esc(ROTULOS_ENTIDADE[ev.entidade] || ev.entidade)}</td>
      <td>${esc(ev.descricao)}</td>
    </tr>`).join("");

  tbody.innerHTML = reiniciar || auditoriaState.offset === 0
    ? (linhas || `<tr><td colspan="5">Nenhum evento registrado.</td></tr>`)
    : tbody.innerHTML + linhas;

  auditoriaState.offset += resultado.itens.length;
  document.getElementById("btn-auditoria-mais").style.display =
    auditoriaState.offset < resultado.total ? "" : "none";
}

let buscaAuditoriaTimer;
document.getElementById("auditoria-busca").addEventListener("input", () => {
  clearTimeout(buscaAuditoriaTimer);
  buscaAuditoriaTimer = setTimeout(() => carregarAuditoria(true), 300);
});
document.getElementById("auditoria-entidade").addEventListener("change", () => carregarAuditoria(true));
document.getElementById("btn-auditoria-mais").addEventListener("click", () => carregarAuditoria(false));

// ---------- INIT ----------
verificarSessao();
