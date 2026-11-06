// Runs a program in the terminal and reports its end to the extension.
const { spawn } = require('child_process');
const fs = require('fs');

const [marca, comando, ...args] = process.argv.slice(2);
const ambiente = { ...process.env };
delete ambiente.ELECTRON_RUN_AS_NODE;
delete ambiente.IJ_FIM;

process.on('SIGINT', () => {});
const filho = spawn(comando, args, { stdio: 'inherit', env: ambiente });

const parar = setInterval(() => {
    if (fs.existsSync(`${marca}.stop`)) {
        fs.rmSync(`${marca}.stop`, { force: true });
        filho.kill();
    }
}, 300);

function terminar(codigo) {
    clearInterval(parar);
    fs.writeFileSync(marca, '');
    process.stdout.write(`\n\x1b[2mProcess finished with exit code ${codigo}\x1b[0m\n`);
    setInterval(() => {}, 1 << 30);
}

filho.on('error', erro => {
    console.error(erro.message);
    terminar(1);
});
filho.on('close', (codigo, sinal) => terminar(codigo ?? (sinal === 'SIGINT' ? 130 : 1)));
