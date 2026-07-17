const state = {
  usuario: null,
  materiais: [],
  clientes: [],
  projetos: [],
  projetoAtual: null,
};

// ---------- HELPERS ----------
async function api(url, options = {}) {
  const opts = { credentials: "include", headers: {}, ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(url, opts);
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

function ehAdmin() {
  return state.usuario && (state.usuario.perfil === "master" || state.usuario.perfil === "administrador");
}

function aplicarPermissoes() {
  document.querySelectorAll(".somente-admin").forEach((el) => {
    el.style.display = ehAdmin() ? "" : "none";
  });
}

function abrirModal(html, extraClass = "") {
  const modal = document.getElementById("modal-conteudo");
  modal.className = `modal ${extraClass}`.trim();
  modal.innerHTML = html;
  document.getElementById("modal-overlay").classList.remove("oculto");
}
function fecharModal() {
  document.getElementById("modal-overlay").classList.add("oculto");
}
document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "modal-overlay") fecharModal();
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

function mostrarApp() {
  document.getElementById("tela-login").classList.add("oculto");
  document.getElementById("app").classList.remove("oculto");
  document.getElementById("usuario-nome").textContent = state.usuario.nome;
  document.getElementById("usuario-perfil").textContent = state.usuario.perfil;
  aplicarPermissoes();
  ativarTab("dashboard");
  carregarDashboard();
}

// ---------- NAVEGAÇÃO ----------
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => ativarTab(btn.dataset.tab));
});

function ativarTab(nome) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("ativo", b.dataset.tab === nome));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("ativo"));
  document.getElementById(`tab-${nome}`).classList.add("ativo");
  if (nome === "materiais") carregarMateriais();
  if (nome === "clientes") carregarClientes();
  if (nome === "projetos") carregarProjetos();
  if (nome === "usuarios") carregarUsuarios();
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
}

function ativarTabInterna(nome) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("ativo"));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("ativo"));
  document.getElementById(`tab-${nome}`).classList.add("ativo");
}

// ---------- DASHBOARD ----------
const CORES_STATUS = {
  planejamento: "var(--viz-serie-1)",
  em_andamento: "var(--viz-serie-3)",
  concluido: "var(--viz-serie-2)",
  cancelado: "var(--viz-serie-6)",
};
const ROTULOS_STATUS = {
  planejamento: "Planejamento", em_andamento: "Em andamento", concluido: "Concluído", cancelado: "Cancelado",
};
const ORDEM_STATUS = ["planejamento", "em_andamento", "concluido", "cancelado"];

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
async function carregarMateriais(busca = "") {
  const url = busca ? `/api/materiais?q=${encodeURIComponent(busca)}` : "/api/materiais";
  state.materiais = await api(url);
  const tbody = document.getElementById("tbody-materiais");
  tbody.innerHTML = state.materiais.map((m) => `
    <tr>
      <td>${m.codigo}</td><td>${m.descricao}</td><td>${m.fabricante || ""}</td>
      <td>${m.bitola || ""}</td><td>${m.unidade}</td>
      <td class="somente-admin">
        <button class="link-acao" onclick="editarMaterial(${m.id})">Editar</button>
        <button class="link-acao" onclick="excluirMaterial(${m.id})">Excluir</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="6">Nenhum material cadastrado.</td></tr>`;
  aplicarPermissoes();
}

let buscaMateriaisTimer;
document.getElementById("materiais-busca").addEventListener("input", (e) => {
  clearTimeout(buscaMateriaisTimer);
  buscaMateriaisTimer = setTimeout(() => carregarMateriais(e.target.value), 300);
});

function modalMaterial(material = null) {
  const m = material || { codigo: "", descricao: "", fabricante: "", bitola: "", unidade: "" };
  abrirModal(`
    <h3>${material ? "Editar" : "Novo"} Material</h3>
    <div class="form-grid">
      <label>Código</label><input id="mat-codigo" value="${m.codigo}">
      <label>Descrição</label><input id="mat-descricao" value="${m.descricao}">
      <label>Fabricante</label><input id="mat-fabricante" value="${m.fabricante || ""}">
      <label>Bitola</label><input id="mat-bitola" value="${m.bitola || ""}">
      <label>Unidade</label><input id="mat-unidade" value="${m.unidade}">
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModal()">Cancelar</button>
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
  };
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
  if (!confirm("Excluir este material?")) return;
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
  const formData = new FormData();
  formData.append("arquivo", arquivo);
  try {
    const resultado = await api("/api/materiais/importar/excel", { method: "POST", body: formData });
    toast(`Importado: ${resultado.inseridos} novos, ${resultado.atualizados} atualizados`);
    carregarMateriais();
  } catch (err) { toast(err.message, "erro"); }
  e.target.value = "";
});

// ---------- CLIENTES ----------
async function carregarClientes(busca = "") {
  const url = busca ? `/api/clientes?q=${encodeURIComponent(busca)}` : "/api/clientes";
  state.clientes = await api(url);
  const tbody = document.getElementById("tbody-clientes");
  tbody.innerHTML = state.clientes.map((c) => `
    <tr>
      <td>${c.razao_social}</td><td>${c.nome_fantasia || ""}</td><td>${c.cnpj_cpf || ""}</td>
      <td>${c.contato || ""}</td><td>${c.telefone || ""}</td>
      <td class="somente-admin">
        <button class="link-acao" onclick="editarCliente(${c.id})">Editar</button>
        <button class="link-acao" onclick="excluirCliente(${c.id})">Excluir</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="6">Nenhum cliente cadastrado.</td></tr>`;
  aplicarPermissoes();
}

let buscaClientesTimer;
document.getElementById("clientes-busca").addEventListener("input", (e) => {
  clearTimeout(buscaClientesTimer);
  buscaClientesTimer = setTimeout(() => carregarClientes(e.target.value), 300);
});

function modalCliente(cliente = null) {
  const c = cliente || { razao_social: "", nome_fantasia: "", cnpj_cpf: "", contato: "", telefone: "", email: "", endereco: "" };
  abrirModal(`
    <h3>${cliente ? "Editar" : "Novo"} Cliente</h3>
    <div class="form-grid">
      <label>Razão Social</label><input id="cli-razao" value="${c.razao_social}">
      <label>Nome Fantasia</label><input id="cli-fantasia" value="${c.nome_fantasia || ""}">
      <label>CNPJ/CPF</label><input id="cli-doc" value="${c.cnpj_cpf || ""}">
      <label>Contato</label><input id="cli-contato" value="${c.contato || ""}">
      <label>Telefone</label><input id="cli-telefone" value="${c.telefone || ""}">
      <label>Email</label><input id="cli-email" value="${c.email || ""}">
      <label>Endereço</label><input id="cli-endereco" value="${c.endereco || ""}">
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModal()">Cancelar</button>
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
  if (!confirm("Excluir este cliente?")) return;
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
      <td>${p.codigo}</td><td>${p.nome}</td><td>${p.cliente_nome || "-"}</td><td>${p.status}</td>
      <td class="acoes-linha">
        <button class="link-acao" onclick="abrirProjeto(${p.id})">Abrir</button>
        <button class="link-acao somente-admin" onclick="editarProjeto(${p.id})">Editar</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="5">Nenhum projeto cadastrado.</td></tr>`;
  aplicarPermissoes();
}

async function modalProjeto(projeto = null) {
  if (!state.clientes.length) state.clientes = await api("/api/clientes");
  const p = projeto || { codigo: "", nome: "", cliente_id: "", descricao: "", status: "planejamento" };
  const opcoesClientes = state.clientes.map((c) => `<option value="${c.id}" ${p.cliente_id == c.id ? "selected" : ""}>${c.razao_social}</option>`).join("");
  abrirModal(`
    <h3>${projeto ? "Editar" : "Novo"} Projeto</h3>
    <div class="form-grid">
      <label>Código</label><input id="proj-codigo" value="${p.codigo}">
      <label>Nome</label><input id="proj-nome" value="${p.nome}">
      <label>Cliente</label>
      <select id="proj-cliente"><option value="">-- Selecione --</option>${opcoesClientes}</select>
      <label>Status</label>
      <select id="proj-status">
        ${["planejamento", "em_andamento", "concluido", "cancelado"].map((s) => `<option value="${s}" ${p.status === s ? "selected" : ""}>${s}</option>`).join("")}
      </select>
      <label>Descrição</label><textarea id="proj-descricao" rows="3">${p.descricao || ""}</textarea>
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModal()">Cancelar</button>
      <button class="btn-primario" onclick="salvarProjeto(${projeto ? projeto.id : "null"})">Salvar</button>
    </div>
  `);
}

async function salvarProjeto(id) {
  const payload = {
    codigo: document.getElementById("proj-codigo").value.trim(),
    nome: document.getElementById("proj-nome").value.trim(),
    cliente_id: document.getElementById("proj-cliente").value || null,
    status: document.getElementById("proj-status").value,
    descricao: document.getElementById("proj-descricao").value.trim(),
  };
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
  ativarTabInterna("projeto-detalhe");
  await carregarListas(id);
}

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

function renderNoLista(l) {
  const aberta = arvoreState.expandidas.has(l.id);
  const versoes = arvoreState.versoesPorLista[l.id];
  const ICONE_PASTA = `<svg class="arvore-icone" viewBox="0 0 20 20" fill="none"><path d="M2.5 5.5a1 1 0 0 1 1-1h4l1.5 1.8h7.5a1 1 0 0 1 1 1v8.2a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1V5.5Z" fill="currentColor" fill-opacity=".14" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>`;
  return `
    <div class="arvore-no" data-lista-id="${l.id}">
      <div class="arvore-linha arvore-linha-pasta">
        <button class="arvore-toggle ${aberta ? "aberto" : ""}" onclick="toggleListaArvore(${l.id})" aria-label="Expandir">
          <svg viewBox="0 0 12 12" fill="none"><path d="M4 2.5 8 6l-4 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        ${ICONE_PASTA}
        <span class="arvore-label" onclick="toggleListaArvore(${l.id})">
          <span class="arvore-titulo">${l.numero_desenho}${l.titulo ? " — " + l.titulo : ""}</span>
          <span class="arvore-sub">${l.versao_atual ? "v" + l.versao_atual : "sem versão"}</span>
        </span>
        <span class="arvore-acoes">
          <button class="link-acao" onclick="abrirEditorLista(${l.id})">Abrir</button>
          <button class="link-acao somente-admin" onclick="excluirLista(${l.id})">Excluir</button>
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
  const ICONE_ARQUIVO = `<svg class="arvore-icone" viewBox="0 0 20 20" fill="none"><path d="M6 2.5h6l3 3v10a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1Z" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M12 2.5V6h3" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>`;
  return versoes.map((v) => `
    <div class="arvore-linha arvore-linha-versao">
      <span class="arvore-toggle invisivel"></span>
      ${ICONE_ARQUIVO}
      <span class="arvore-label" onclick="verVersao(${listaId}, ${v.id})">
        <span class="arvore-titulo">v${v.versao}</span>
        <span class="arvore-sub">${new Date(v.criado_em).toLocaleString("pt-BR")} · ${v.criado_por_nome || "-"}</span>
      </span>
      <span class="arvore-acoes">
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

async function excluirLista(id) {
  if (!confirm("Excluir esta lista por desenho e todo seu histórico?")) return;
  await api(`/api/listas/${id}`, { method: "DELETE" });
  toast("Lista excluída");
  carregarListas(state.projetoAtual.id);
}

function modalNovaLista() {
  abrirModal(`
    <h3>Nova Lista por Desenho</h3>
    <div class="form-grid">
      <label>Nº do Desenho</label><input id="lista-numero">
      <label>Título</label><input id="lista-titulo">
      <label>Nº do Cliente</label><input id="lista-numero-cliente">
      <label>Nº do Fornecedor</label><input id="lista-numero-fornecedor">
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModal()">Cancelar</button>
      <button class="btn-primario" onclick="criarLista()">Criar e Abrir</button>
    </div>
  `);
}

async function criarLista() {
  const numero_desenho = document.getElementById("lista-numero").value.trim();
  const titulo = document.getElementById("lista-titulo").value.trim();
  const numero_cliente = document.getElementById("lista-numero-cliente").value.trim();
  const numero_fornecedor = document.getElementById("lista-numero-fornecedor").value.trim();
  if (!numero_desenho) { toast("Informe o número do desenho", "erro"); return; }
  try {
    const resultado = await api(`/api/projetos/${state.projetoAtual.id}/listas`, {
      method: "POST", body: JSON.stringify({ numero_desenho, titulo, numero_cliente, numero_fornecedor, itens: [] }),
    });
    fecharModal();
    await carregarListas(state.projetoAtual.id);
    abrirEditorLista(resultado.id);
  } catch (err) { toast(err.message, "erro"); }
}

document.getElementById("btn-nova-lista").addEventListener("click", modalNovaLista);

// ---------- EDITOR DA LISTA (com versionamento) ----------
async function abrirEditorLista(listaId) {
  if (!state.materiais.length) state.materiais = await api("/api/materiais");
  const dados = await api(`/api/listas/${listaId}`);
  const itensIniciais = dados.itens.map((i) => ({ material_id: i.material_id, codigo: i.codigo, descricao: i.descricao, quantidade: i.quantidade, observacao: i.observacao || "" }));

  renderEditorLista(listaId, dados.lista, itensIniciais);
}

function renderEditorLista(listaId, lista, itens) {
  const rotuloMaterial = (m) => `${m.codigo} — ${m.descricao}`;
  const opcoesDatalist = state.materiais.map((m) => `<option value="${rotuloMaterial(m)}">`).join("");

  const linhaHtml = (item, idx) => `
    <div class="item-linha" data-idx="${idx}">
      <input class="item-material-busca" list="materiais-datalist" placeholder="Buscar por código ou descrição..."
             value="${item.codigo ? rotuloMaterial(item) : ""}">
      <input class="item-qtd" type="number" step="0.001" min="0" value="${item.quantidade}" placeholder="Qtd">
      <input class="item-obs" type="text" value="${item.observacao || ""}" placeholder="Observação">
      <button class="btn-perigo" onclick="removerItemLinha(${idx})">Remover</button>
    </div>`;

  abrirModal(`
    <h3>Lista por Desenho — ${lista.numero_desenho}</h3>
    <div class="form-grid">
      <label>Título</label><input id="editor-titulo" value="${lista.titulo || ""}">
      <label>Nº do Cliente</label><input id="editor-numero-cliente" value="${lista.numero_cliente || ""}">
      <label>Nº do Fornecedor</label><input id="editor-numero-fornecedor" value="${lista.numero_fornecedor || ""}">
    </div>
    <datalist id="materiais-datalist">${opcoesDatalist}</datalist>
    <div class="itens-editor" id="itens-editor"></div>
    <button class="btn-secundario somente-admin" onclick="adicionarItemLinha()">+ Adicionar Material</button>
    <div class="modal-acoes">
      <a class="btn-secundario" href="/api/listas/${listaId}/relatorio/excel" target="_blank">Relatório Excel</a>
      <a class="btn-secundario" href="/api/listas/${listaId}/relatorio/pdf" target="_blank">Relatório PDF</a>
      <span style="flex:1"></span>
      <button class="btn-secundario" onclick="fecharModal()">Cancelar</button>
      <button class="btn-primario somente-admin" onclick="salvarEditorLista(${listaId})">Salvar (nova versão)</button>
    </div>
  `, "modal-grande");
  aplicarPermissoes();

  window._itensEditor = itens.length ? [...itens] : [];
  redesenharItensEditor();

  window.adicionarItemLinha = () => {
    window._itensEditor.push({ material_id: "", quantidade: 1, observacao: "" });
    redesenharItensEditor();
  };
  window.removerItemLinha = (idx) => {
    window._itensEditor.splice(idx, 1);
    redesenharItensEditor();
  };

  function resolverMaterial(texto) {
    const alvo = texto.trim().toLowerCase();
    if (!alvo) return null;
    return state.materiais.find((m) => rotuloMaterial(m).toLowerCase() === alvo);
  }

  function redesenharItensEditor() {
    const cont = document.getElementById("itens-editor");
    cont.innerHTML = window._itensEditor.map(linhaHtml).join("") || "<p>Nenhum material adicionado.</p>";
    cont.querySelectorAll(".item-linha").forEach((linha) => {
      const idx = Number(linha.dataset.idx);
      const item = window._itensEditor[idx];
      const busca = linha.querySelector(".item-material-busca");
      busca.addEventListener("change", () => {
        const material = resolverMaterial(busca.value);
        if (material) {
          item.material_id = material.id;
          busca.value = rotuloMaterial(material);
          busca.classList.remove("invalido");
        } else if (busca.value.trim() === "") {
          item.material_id = "";
          busca.classList.remove("invalido");
        } else {
          item.material_id = "";
          busca.classList.add("invalido");
        }
      });
      linha.querySelector(".item-qtd").addEventListener("input", (e) => { item.quantidade = e.target.value; });
      linha.querySelector(".item-obs").addEventListener("input", (e) => { item.observacao = e.target.value; });
    });
  }
}

async function salvarEditorLista(listaId) {
  const itens = (window._itensEditor || []).filter((i) => i.material_id);
  const payload = {
    titulo: document.getElementById("editor-titulo").value.trim(),
    numero_cliente: document.getElementById("editor-numero-cliente").value.trim(),
    numero_fornecedor: document.getElementById("editor-numero-fornecedor").value.trim(),
    itens: itens.map((i) => ({ material_id: Number(i.material_id), quantidade: Number(i.quantidade) || 0, observacao: i.observacao || "" })),
  };
  try {
    await api(`/api/listas/${listaId}`, { method: "PUT", body: JSON.stringify(payload) });
    fecharModal();
    toast("Nova versão salva com sucesso");
    carregarListas(state.projetoAtual.id);
  } catch (err) { toast(err.message, "erro"); }
}

async function verVersao(listaId, versaoId) {
  const dados = await api(`/api/versoes/${versaoId}`);
  abrirModal(`
    <h3>Versão ${dados.versao.versao}</h3>
    <table class="tabela">
      <thead><tr><th>Código</th><th>Descrição</th><th>Qtd</th><th>Unidade</th></tr></thead>
      <tbody>
        ${dados.itens.map((i) => `<tr><td>${i.codigo}</td><td>${i.descricao}</td><td>${i.quantidade}</td><td>${i.unidade}</td></tr>`).join("") || "<tr><td colspan='4'>Sem itens</td></tr>"}
      </tbody>
    </table>
    <div class="modal-acoes">
      <a class="btn-secundario" href="/api/listas/${listaId}/relatorio/excel?versao_id=${versaoId}" target="_blank">Relatório Excel</a>
      <a class="btn-secundario" href="/api/listas/${listaId}/relatorio/pdf?versao_id=${versaoId}" target="_blank">Relatório PDF</a>
      <span style="flex:1"></span>
      <button class="btn-secundario" onclick="fecharModal()">Fechar</button>
    </div>
  `);
}

// ---------- USUÁRIOS ----------
async function carregarUsuarios() {
  const usuarios = await api("/api/usuarios");
  const tbody = document.getElementById("tbody-usuarios");
  tbody.innerHTML = usuarios.map((u) => `
    <tr>
      <td>${u.nome}</td><td>${u.email}</td><td>${u.perfil}</td><td>${u.ativo ? "Sim" : "Não"}</td>
      <td class="acoes-linha">
        <button class="link-acao" onclick='editarUsuario(${JSON.stringify(u)})'>Editar</button>
        <button class="link-acao" onclick="excluirUsuario(${u.id})">Desativar</button>
      </td>
    </tr>`).join("");
}

function modalUsuario(usuario = null) {
  const u = usuario || { nome: "", email: "", perfil: "visualizador", ativo: 1 };
  abrirModal(`
    <h3>${usuario ? "Editar" : "Novo"} Usuário</h3>
    <div class="form-grid">
      <label>Nome</label><input id="usr-nome" value="${u.nome}">
      <label>Email</label><input id="usr-email" value="${u.email}" ${usuario ? "disabled" : ""}>
      <label>Perfil</label>
      <select id="usr-perfil">
        ${["master", "administrador", "visualizador"].map((p) => `<option value="${p}" ${u.perfil === p ? "selected" : ""}>${p}</option>`).join("")}
      </select>
      <label>Senha ${usuario ? "(deixe em branco para não alterar)" : ""}</label>
      <input id="usr-senha" type="password">
    </div>
    <div class="modal-acoes">
      <button class="btn-secundario" onclick="fecharModal()">Cancelar</button>
      <button class="btn-primario" onclick="salvarUsuario(${usuario ? usuario.id : "null"})">Salvar</button>
    </div>
  `);
}

async function salvarUsuario(id) {
  const senha = document.getElementById("usr-senha").value;
  try {
    if (id) {
      const payload = { nome: document.getElementById("usr-nome").value.trim(), perfil: document.getElementById("usr-perfil").value, ativo: 1 };
      if (senha) payload.senha = senha;
      await api(`/api/usuarios/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      const payload = {
        nome: document.getElementById("usr-nome").value.trim(),
        email: document.getElementById("usr-email").value.trim(),
        perfil: document.getElementById("usr-perfil").value,
        senha,
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
  if (!confirm("Desativar este usuário?")) return;
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
}

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
      <td>${ev.usuario_nome}</td>
      <td><span class="badge-acao ${ev.acao}">${ROTULOS_ACAO[ev.acao] || ev.acao}</span></td>
      <td>${ROTULOS_ENTIDADE[ev.entidade] || ev.entidade}</td>
      <td>${ev.descricao}</td>
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
