# Terminal do perfil Java: prompt curto e saída de execução limpa, como a janela Run do IntelliJ
[ -f ~/.bashrc ] && . ~/.bashrc
PS1='\[\e[2m\]\W >\[\e[0m\] '

_java_rodando=0
_ao_comando() {
    case "$BASH_COMMAND" in
        *bin/java\ *) _java_rodando=1; printf '\e[H\e[2J\e[3J' ;;
    esac
}
_fim_java() {
    local codigo=$?
    if [ "$_java_rodando" = 1 ]; then
        _java_rodando=0
        printf '\n\e[2mProcess finished with exit code %s\e[0m\n\n' "$codigo"
    fi
}
PROMPT_COMMAND=(_fim_java "${PROMPT_COMMAND[@]}")
trap _ao_comando DEBUG
