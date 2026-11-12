import math

Quaternion = tuple[float, float, float, float]
Matrix3 = list[list[float]]


class Rotation:
    @staticmethod
    def from_quat(value: Quaternion) -> Quaternion:
        return value


def conjugate(value: Quaternion) -> Quaternion:
    w, x, y, z = value
    return w, -x, -y, -z


def multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def conjugate_quaternion(w: float, x: float, y: float, z: float) -> Quaternion:
    return w, -x, -y, -z


def multiply_quaternions(
    lw: float,
    lx: float,
    ly: float,
    lz: float,
    rw: float,
    rx: float,
    ry: float,
    rz: float,
) -> Quaternion:
    ow, ox, oy, oz = (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )
    return ow, ox, oy, oz


def normalize_attitude(w: float, x: float, y: float, z: float) -> Quaternion:
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    unit = (w / norm, x / norm, y / norm, z / norm)
    return Rotation.from_quat(unit)


def inverse_quaternion(w: float, x: float, y: float, z: float) -> Quaternion:
    norm_squared = w * w + x * x + y * y + z * z
    return (w / norm_squared, -x / norm_squared, -y / norm_squared, -z / norm_squared)


def rotate_vector(
    w: float, x: float, y: float, z: float, vx: float, vy: float, vz: float
) -> Quaternion:
    return multiply(multiply((w, x, y, z), (0, vx, vy, vz)), conjugate((w, x, y, z)))


def quaternion_to_matrix(w: float, x: float, y: float, z: float) -> Matrix3:
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
