#!/usr/bin/env python

import os
import pcbnew
from pcbnew import wxPoint, TRACK, VIA, SaveBoard
from math import sqrt
from functools import reduce
# from .bga_utils import * # get_bga_info

class BgaInfo:
    spacing = 0.0
    rows = 0
    columns = 0
    center = pcbnew.wxPoint(0,0)

def detect_spacing(module):
    is_first = True
    min_dist = 100000000000
    for pad in module.Pads():
        if is_first:
            first_pad = pad
            is_first = False
        elif first_pad.GetPosition().x != pad.GetPosition().x:
            min_dist = min(min_dist, abs(first_pad.GetPosition().x - pad.GetPosition().x))
    return min_dist

def get_node_counts(board, pad):
    net_id = 0
    net_id_counts = 0
    net_id = pad.GetNet().GetNet()
    net_id_counts = board.GetNodesCount(net_id)
    return net_id_counts

def get_first_pad(board, module):
    net_id = 0
    net_id_counts = 0
    for pad in filter(lambda p: get_node_counts(board, p) > 1, module.Pads()):
        return pad
    return None

def get_bga_info(module):
    info = BgaInfo()
    info.spacing = detect_spacing(module)

    minx = reduce(lambda x, y: min(x, y), map(lambda x: x.GetPosition().x, module.Pads()))
    maxx = reduce(lambda x, y: max(x, y), map(lambda x: x.GetPosition().x, module.Pads()))
    miny = reduce(lambda x, y: min(x, y), map(lambda x: x.GetPosition().y, module.Pads()))
    maxy = reduce(lambda x, y: max(x, y), map(lambda x: x.GetPosition().y, module.Pads()))

    info.origin = pcbnew.wxPoint(minx, miny)

    info.rows = int(1+round((maxy-miny)/float(info.spacing)))
    info.columns = int(1+round((maxx-minx)/float(info.spacing)))

    # Assemble pad grid
    info.pad_grid = {}
    for x in range(0,info.columns):
        info.pad_grid[x] = {}
        for y in range(0,info.rows):
            info.pad_grid[x][y] = False
    for pad in module.Pads():
        xy = pcbnew.wxPoint(round((pad.GetPosition().x-minx)/float(info.spacing)), round((pad.GetPosition().y-miny)/float(info.spacing)))
        info.pad_grid[xy.x][xy.y] = True

    info.center = pcbnew.wxPoint(maxx* 0.5 + minx* 0.5, maxy * 0.5 + miny* 0.5)
    return info


def get_pad_position(bga_info, pad):
    offset = pad.GetPosition()-bga_info.center
    return wxPoint(int(offset.x/bga_info.spacing), int(offset.y/bga_info.spacing))+wxPoint(bga_info.columns/2, bga_info.rows/2)


def is_pad_outer_ring(bga_info, pad_pos, rows):
    return (pad_pos.x<rows) or (pad_pos.y<rows) or ((bga_info.columns-pad_pos.x)<=rows) or ((bga_info.rows-pad_pos.y)<=rows)


def is_edge_layer(bga_info, pad_pos, rows):
    return is_pad_outer_ring(bga_info,pad_pos,rows) and \
           (((pad_pos.x>=rows) and ((bga_info.columns-pad_pos.x)>rows)) !=
            ((pad_pos.y>=rows) and ((bga_info.rows-pad_pos.y)>rows)))



def get_net_classes(board, vias, except_names):
    net_list = list(set(map(lambda x: x.GetNet().GetClassName(), vias)))
    net_list = filter(lambda x: not (x in except_names), net_list)
    return filter(lambda x: x != "Default", net_list)


def get_signal_layers(board):
    return filter(lambda x: IsCopperLayer(x) and (board.GetLayerType(x)==LT_SIGNAL), board.GetEnabledLayers().Seq())


def get_all_pads(board, from_module):
    lst = list()
    for mod in board.GetModules():
        if mod != from_module:
            lst = lst + list(mod.Pads())
    return lst


def get_connection_dest(via, all_pads):
    connected_pads = filter(lambda x: x.GetNetname() == via.GetNetname(), all_pads)
    count = len(connected_pads)
    if(count == 0):
        return wxPoint(0,0)
    p = reduce(lambda x,y: x+y, map(lambda x: x.GetPosition(), connected_pads), wxPoint(0,0))
    return wxPoint(p.x/count, p.y/count)


def pos_to_local(mod_info, via):
    pos = via.GetPosition()
    ofs = pos - mod_info.center
    px = int(round(ofs.x/float(mod_info.spacing)))+mod_info.columns/2
    py = int(round(ofs.y/float(mod_info.spacing)))+mod_info.rows/2
    return wxPoint(px,py)

def make_dogbone(board, mod, bga_info, skip_outer, edge_layers):
    vias = []

    net = get_first_pad(board, mod).GetNet()

    via_dia = net.GetViaSize()
    isolation = net.GetClearance(None)
    dist = bga_info.spacing

    fy = sqrt((isolation+via_dia)**2-(dist/2)**2)
    fx = sqrt((isolation+via_dia)**2-fy**2)

    ofsx = fx/2
    ofsy = (dist-fy)/2

    for pad in filter(lambda p: get_node_counts(board, p) > 1, mod.Pads()):
        pad_pos = get_pad_position(bga_info, pad)
        if is_pad_outer_ring(bga_info, pad_pos, skip_outer):
            continue
        if is_edge_layer(bga_info,pad_pos,edge_layers):
            horizontal = abs(pad.GetPosition().x - bga_info.center.x) > abs(pad.GetPosition().y - bga_info.center.y)

            if horizontal:
                if (pad_pos.y-edge_layers) % 2 == 0:
                    ep = pad.GetPosition() + wxPoint(ofsx, -ofsy)
                else:
                    ep = pad.GetPosition() + wxPoint(-ofsx, ofsy)
            else:
                if (pad_pos.x-edge_layers) % 2 == 0:
                    ep = pad.GetPosition() + wxPoint(ofsy, -ofsx)
                else:
                    ep = pad.GetPosition() + wxPoint(-ofsy, ofsx)
        elif (edge_layers>0) and is_edge_layer(bga_info,pad_pos,edge_layers+1):
            horizontal = abs(pad.GetPosition().x - bga_info.center.x) > abs(pad.GetPosition().y - bga_info.center.y)

            dx = 1 if (pad.GetPosition().x - bga_info.center.x) > 0 else -1
            dy = 1 if (pad.GetPosition().y - bga_info.center.y) > 0 else -1

            if horizontal:
                ep = pad.GetPosition() + wxPoint(dx * ofsx, -dx * ofsy)
            else:
                ep = pad.GetPosition() + wxPoint(-dy * ofsy, dy * ofsx)
        else:
            dx = 1 if (pad.GetPosition().x - bga_info.center.x) > 0 else -1
            dy = 1 if (pad.GetPosition().y - bga_info.center.y) > 0 else -1
            ep = pad.GetPosition() + wxPoint(dx * bga_info.spacing / 2, dy * bga_info.spacing / 2)

        # Create track
        new_track = TRACK(board)
        new_track.SetStart(pad.GetPosition())
        new_track.SetEnd(ep)
        new_track.SetNetCode(pad.GetNetCode())
        new_track.SetLayer(pad.GetLayer())
        board.Add(new_track)
        # Create via
        new_via = VIA(board)
        new_via.SetPosition(ep)
        new_via.SetNetCode(pad.GetNetCode())
        new_via.SetDrill(int(pad.GetNet().GetViaDrillSize() / 2))
        new_via.SetWidth(int(pad.GetNet().GetViaSize() / 2))
        board.Add(new_via)
        vias.append(new_via)
    return vias


def make_dogbones(board, mod, skip_outer, edge_layers):
    info = get_bga_info(mod)
    return [info.spacing, make_dogbone(board, mod, info, skip_outer, edge_layers)]

class bgafanout(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "bga fanout"
        self.category = "A descriptive category name"
        self.description = "A description of the plugin and what it does"
        self.show_toolbar_button = True # Optional, defaults to False
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'bg_add.png') # Optional, defaults to ""

    def Run(self):
        board = pcbnew.GetBoard()
        pcb_file_name = board.GetFileName()
        pcb_board = pcbnew.LoadBoard(pcb_file_name)
        pcb_board.BuildListOfNets()
    #
        mod = pcb_board.FindModuleByReference("U8")
    #
    ## Skip zero layers and route 6 layer quadrants with shifted vias and 1 transition layer
        data = make_dogbones(pcb_board, mod, 1, 0)
        SaveBoard('t1.kicad_pcb', pcb_board)
        # The entry function of the plugin that is executed on user action

bgafanout().register() # Instantiate and register to Pcbnew
