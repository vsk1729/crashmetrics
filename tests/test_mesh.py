"""Tests for crashmetrics.mesh (keyword mesh reader and writer)."""

import numpy as np
import pytest

from crashmetrics.mesh import read_mesh, write_mesh

FIXED = """*KEYWORD
$ a comment
*TITLE
small deck
*PART
Bonnet outer
       100         1         1
*PART_CONTACT
Engine
       401         2         2
$  extra contact card of *PART_CONTACT
       0.1       0.1
*SECTION_SHELL
         1
*NODE
       1             0.0             0.0           100.0
       2            10.0             0.0           100.0
       3            10.0            10.0           100.0
       4             0.0            10.0           100.0
       5             0.0             0.0            50.0
       6            10.0             0.0            50.0
       7            10.0            10.0            50.0
       8             0.0            10.0            50.0
       5             0.0             0.0            40.0
*ELEMENT_SHELL
       1     100       1       2       3       4
*ELEMENT_SHELL_THICKNESS
       2     401       5       6       7       8
       1.0       1.0       1.0       1.0
*ELEMENT_SOLID
      10     402       1       2       3       4       5       6       7       8
*ELEMENT_BEAM
      20     403       1       5       0
*END
"""


def test_fixed_format(tmp_path):
    path = tmp_path / "deck.k"
    path.write_text(FIXED)
    mesh = read_mesh(path)
    assert len(mesh.node_ids) == 8
    assert mesh.part_names == {100: "Bonnet outer", 401: "Engine"}
    assert mesh.part_ids == (100, 401, 402, 403)
    assert mesh.part_name(402) == "Part 402"
    assert mesh.elements["shell"][2] == (401, (5, 6, 7, 8))   # thickness card skipped
    assert mesh.elements["solid"][10][1] == tuple(range(1, 9))
    assert mesh.elements["beam"][20] == (403, (1, 5))
    np.testing.assert_allclose(mesh.coordinates_of([5]), [[0.0, 0.0, 40.0]])  # last
    assert mesh.points(401).shape == (4, 3)
    assert mesh.points([100, 401]).shape == (8, 3)
    assert mesh.find_parts("eng*") == [401]
    with pytest.raises(KeyError, match="No elements of part 999"):
        mesh.points(999)
    with pytest.raises(KeyError, match="Nodes not in the mesh"):
        mesh.coordinates_of([99])
    only = read_mesh(path, parts=[100])
    assert only.part_ids == (100,) and len(only.node_ids) == 8


def test_long_and_comma_formats_and_merge(tmp_path):
    long = tmp_path / "long.k"
    long.write_text("*KEYWORD\n*NODE +\n"
                    f"{11:20d}{1.5:32.6f}{2.5:32.6f}{-3.5:32.6f}\n"
                    f"{12:20d}{1.0:32.6f}{2.0:32.6f}{3.0:32.6f}\n"
                    "*ELEMENT_BEAM +\n" f"{1:20d}{7:20d}{11:20d}{12:20d}\n*END\n")
    comma = tmp_path / "comma.k"
    comma.write_text("*NODE\n21, 1.0, 2.0, 3.5e+2\n22,4,5,6\n"
                     "*ELEMENT_SHELL\n5, 8, 21, 22, 22, 21\n*END\n")
    a, b = read_mesh(long), read_mesh(comma)
    np.testing.assert_allclose(a.coordinates_of([11]), [[1.5, 2.5, -3.5]])
    assert a.elements["beam"][1] == (7, (11, 12))
    np.testing.assert_allclose(b.coordinates_of([21]), [[1.0, 2.0, 350.0]])
    both = a.merge(b)
    assert both.part_ids == (7, 8) and len(both.node_ids) == 4
    assert ";" in both.source


def test_write_round_trip_and_errors(tmp_path):
    xyz = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.25]], dtype=float)
    path = write_mesh(tmp_path / "w.k", [1, 2, 3, 4], xyz, {1: (5, [1, 2, 3, 4])},
                      {5: "Plate"}, title="round trip")
    mesh = read_mesh(path)
    np.testing.assert_allclose(mesh.points(5), xyz)
    assert mesh.part_names == {5: "Plate"}
    empty = tmp_path / "empty.k"
    empty.write_text("*KEYWORD\n*END\n")
    with pytest.raises(ValueError, match="No \\*NODE"):
        read_mesh(empty)
