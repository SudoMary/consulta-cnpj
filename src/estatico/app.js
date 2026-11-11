// Melhorias de usabilidade. O site funciona sem este arquivo: a validação que
// vale é a do servidor, e a busca é um formulário comum.
(function () {
  "use strict";

  // Tema: automático (segue o sistema), claro ou escuro. A escolha fica salva
  // neste navegador; o <head> a aplica antes de desenhar a página.
  var raiz = document.documentElement;
  var botaoTema = document.getElementById("alternar-tema");
  var ordem = ["automatico", "claro", "escuro"];
  var nomes = { automatico: "Tema automático", claro: "Tema claro", escuro: "Tema escuro" };

  function temaSalvo() {
    try {
      var tema = localStorage.getItem("tema");
      return tema === "claro" || tema === "escuro" ? tema : "automatico";
    } catch (e) {
      return "automatico";
    }
  }

  function aplicarTema(tema) {
    if (tema === "claro") raiz.setAttribute("data-theme", "light");
    else if (tema === "escuro") raiz.setAttribute("data-theme", "dark");
    else raiz.removeAttribute("data-theme");
    if (botaoTema) botaoTema.textContent = nomes[tema];
  }

  if (botaoTema) {
    var temaAtual = temaSalvo();
    aplicarTema(temaAtual);
    botaoTema.hidden = false;
    botaoTema.addEventListener("click", function () {
      temaAtual = ordem[(ordem.indexOf(temaAtual) + 1) % ordem.length];
      try {
        if (temaAtual === "automatico") localStorage.removeItem("tema");
        else localStorage.setItem("tema", temaAtual);
      } catch (e) {}
      aplicarTema(temaAtual);
    });
  }

  // Busca: máscara e conferência do dígito verificador enquanto se digita.
  // É a mesma conta de src/validacao.py, mostrada antes de ir ao servidor.
  var PESOS_DV1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  var PESOS_DV2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];

  function digitoVerificador(digitos, pesos) {
    var soma = 0;
    for (var i = 0; i < pesos.length; i++) soma += Number(digitos[i]) * pesos[i];
    var resto = soma % 11;
    return resto < 2 ? 0 : 11 - resto;
  }

  function cnpjValido(digitos) {
    if (digitos.length !== 14 || /^(\d)\1{13}$/.test(digitos)) return false;
    return (
      digitoVerificador(digitos, PESOS_DV1) === Number(digitos[12]) &&
      digitoVerificador(digitos, PESOS_DV2) === Number(digitos[13])
    );
  }

  function mascarar(d) {
    var texto = d.slice(0, 2);
    if (d.length > 2) texto += "." + d.slice(2, 5);
    if (d.length > 5) texto += "." + d.slice(5, 8);
    if (d.length > 8) texto += "/" + d.slice(8, 12);
    if (d.length > 12) texto += "-" + d.slice(12, 14);
    return texto;
  }

  var formulario = document.getElementById("form-busca");
  var campo = document.getElementById("campo-cnpj");
  var dica = document.getElementById("dica-cnpj");

  function avaliar() {
    var digitos = campo.value.replace(/\D/g, "").slice(0, 14);
    campo.value = mascarar(digitos);
    var classe = "dica";
    var texto;
    if (digitos.length === 0) {
      texto = "Pode digitar ou colar, com ou sem pontuação.";
    } else if (digitos.length < 14) {
      var faltam = 14 - digitos.length;
      texto = "Faltam " + faltam + (faltam === 1 ? " dígito." : " dígitos.");
    } else if (cnpjValido(digitos)) {
      classe += " ok";
      texto = "Dígitos verificadores conferem. Pode consultar.";
    } else {
      classe += " grave";
      texto = "Os dígitos verificadores não conferem. Confira o número digitado.";
    }
    dica.className = classe;
    dica.textContent = texto;
    campo.setAttribute("aria-invalid", classe.indexOf("grave") >= 0 ? "true" : "false");
    return cnpjValido(digitos);
  }

  if (formulario && campo && dica) {
    if (campo.value) campo.value = mascarar(campo.value.replace(/\D/g, "").slice(0, 14));
    campo.addEventListener("input", avaliar);
    formulario.addEventListener("submit", function (evento) {
      if (!avaliar()) {
        evento.preventDefault();
        campo.focus();
      }
    });
  }

  // Copiar o CNPJ, quando o navegador permite.
  var botoesCopiar = document.querySelectorAll("[data-copiar]");
  if (navigator.clipboard) {
    botoesCopiar.forEach(function (botao) {
      botao.hidden = false;
      botao.addEventListener("click", function () {
        var original = botao.textContent;
        navigator.clipboard.writeText(botao.getAttribute("data-copiar")).then(
          function () {
            botao.textContent = "Copiado";
            setTimeout(function () { botao.textContent = original; }, 1600);
          },
          function () {}
        );
      });
    });
  }
})();
