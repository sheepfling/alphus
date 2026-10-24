int route(int state, bool enabled) {
    if (enabled && state > 0) {
        switch (state) {
        case 1:
        case 2:
            return 1;
        case 3:
            return state > 5 ? 5 : state;
        default:
            return -1;
        }
    }
    return 0;
}
