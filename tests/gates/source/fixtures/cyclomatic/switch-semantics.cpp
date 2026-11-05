int switch_cases(int value) {
    switch (value) {
    case 0:
    case 1:
        return 1;
    case 2:
        return 2;
    default:
        return -1;
    }
}

int nested_switch(int value, bool enabled) {
    if (enabled && value > 0) {
        switch (value) {
        case 1:
            return 1;
        case 2:
            return 2;
        default:
            return value > 5 ? 5 : value;
        }
    }
    return 0;
}
