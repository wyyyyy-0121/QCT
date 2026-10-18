"""Complete restricted string parsing; execution and provenance, not repair authority."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from typed_execution_adapter import ExcelError

VERSION='typed-string-execution-dev28-v1'
MAX_CHARACTERS=8192
MAX_NODES=512
MAX_DEPTH=64
MAX_UTF16_UNITS=32767
ADDRESS=re.compile(r'(\$?)([A-Za-z]{1,3})(\$?)([1-9][0-9]*)')


class Unsupported(ValueError):
    def __init__(self,code):super().__init__(code);self.code=code


@dataclass(frozen=True)
class Text:
    value:str


@dataclass(frozen=True)
class Integer:
    value:int


@dataclass(frozen=True)
class Reference:
    sheet:str|None
    address:str
    column_absolute:bool
    row_absolute:bool
    offset:int


@dataclass(frozen=True)
class Concat:
    parts:tuple


class Parser:
    def __init__(self,formula):
        if not isinstance(formula,str) or not formula.startswith('='):raise Unsupported('missing_formula')
        if len(formula)>MAX_CHARACTERS:raise Unsupported('formula_budget')
        self.text=formula;self.i=1;self.nodes=0

    def space(self):
        while self.i<len(self.text) and self.text[self.i].isspace():self.i+=1

    def node(self,value):
        self.nodes+=1
        if self.nodes>MAX_NODES:raise Unsupported('node_budget')
        return value

    def expression(self,depth):
        if depth>MAX_DEPTH:raise Unsupported('depth_budget')
        parts=[self.atom(depth)];self.space()
        while self.i<len(self.text) and self.text[self.i]=='&':
            self.i+=1;parts.append(self.atom(depth));self.space()
        return parts[0] if len(parts)==1 else self.node(Concat(tuple(parts)))

    def atom(self,depth):
        self.space();start=self.i
        if self.i>=len(self.text):raise Unsupported('missing_operand')
        char=self.text[self.i]
        if char=='"':
            self.i+=1;value=[]
            while self.i<len(self.text):
                if self.text[self.i]=='"':
                    if self.i+1<len(self.text) and self.text[self.i+1]=='"':value.append('"');self.i+=2;continue
                    self.i+=1;return self.node(Text(''.join(value)))
                value.append(self.text[self.i]);self.i+=1
            raise Unsupported('unterminated_string')
        if char=='(':
            self.i+=1;result=self.expression(depth+1);self.space()
            if self.i>=len(self.text) or self.text[self.i]!=')':raise Unsupported('missing_parenthesis')
            self.i+=1;return result
        number=re.match(r'-?[0-9]+',self.text[self.i:])
        if number:
            self.i+=len(number.group());value=int(number.group())
            if abs(value)>999999999999999:raise Unsupported('integer_precision')
            return self.node(Integer(value))
        sheet=None
        if char=="'":
            self.i+=1;name=[]
            while self.i<len(self.text):
                if self.text[self.i]=="'":
                    if self.i+1<len(self.text) and self.text[self.i+1]=="'":name.append("'");self.i+=2;continue
                    self.i+=1;break
                name.append(self.text[self.i]);self.i+=1
            else:raise Unsupported('unterminated_sheet')
            sheet=''.join(name)
            if not sheet or any(x in sheet for x in '[]:*?/\\'):raise Unsupported('unsupported_sheet_reference')
            if self.i>=len(self.text) or self.text[self.i]!='!':raise Unsupported('missing_sheet_separator')
            self.i+=1
        else:
            function=re.match(r'[A-Za-z_][A-Za-z_0-9.]*\s*\(',self.text[self.i:])
            if function:
                name=function.group().split('(')[0].strip().upper()
                if name!='CONCATENATE':raise Unsupported('unsupported_function')
                self.i+=len(function.group());parts=[];self.space()
                if self.i<len(self.text) and self.text[self.i]==')':raise Unsupported('empty_function')
                while True:
                    parts.append(self.expression(depth+1));self.space()
                    if self.i>=len(self.text):raise Unsupported('missing_parenthesis')
                    if self.text[self.i]==')':self.i+=1;break
                    if self.text[self.i]!=',':raise Unsupported('unsupported_argument_separator')
                    self.i+=1
                return self.node(Concat(tuple(parts)))
            qualifier=re.match(r'[A-Za-z_][A-Za-z_0-9.]*!',self.text[self.i:])
            if qualifier:sheet=qualifier.group()[:-1];self.i+=len(qualifier.group())
        address=ADDRESS.match(self.text,self.i)
        if address is None:raise Unsupported('unsupported_token')
        self.i=address.end();col=address.group(2).upper();row=int(address.group(4));column=0
        for c in col:column=column*26+ord(c)-64
        if row>1048576 or column>16384:raise Unsupported('reference_outside_grid')
        return self.node(Reference(sheet,col+str(row),bool(address.group(1)),bool(address.group(3)),start))

    def parse(self):
        result=self.expression(0);self.space()
        if self.i!=len(self.text):raise Unsupported('trailing_or_unsupported_expression')
        return result


def parse(formula):return Parser(formula).parse()


def provenance(node,current_sheet):
    result=[];pending=[(node,())]
    while pending:
        n,path=pending.pop()
        if isinstance(n,Reference):
            result.append(dict(sheet=n.sheet or current_sheet,address=n.address,column_absolute=n.column_absolute,
                               row_absolute=n.row_absolute,ast_path=list(path),formula_offset=n.offset))
        elif isinstance(n,Concat):pending.extend((v,path+(i,)) for i,v in reversed(list(enumerate(n.parts))))
    return result


def _string(value):
    if isinstance(value,ExcelError):return value
    if value is None:return ''
    if isinstance(value,str):return value
    if isinstance(value,bool):return 'TRUE' if value else 'FALSE'
    if isinstance(value,(int,float)) and abs(value)<=999999999999999 and int(value)==value:return str(int(value))
    raise Unsupported('unsupported_scalar_text_conversion')


def execute(node,current_sheet,inputs:Mapping,formula_cells=(),sheet_names=None):
    formula_cells=set(formula_cells)
    names=set(sheet_names) if sheet_names is not None else {key[0] for key in inputs}|{key[0] for key in formula_cells}|{current_sheet}
    def evaluate(n):
        if isinstance(n,Text):return n.value
        if isinstance(n,Integer):return n.value
        if isinstance(n,Reference):
            requested=n.sheet or current_sheet
            matches=[name for name in names if name.casefold()==requested.casefold()]
            if len(matches)!=1:return ExcelError('#REF!')
            key=(matches[0],n.address)
            if key in formula_cells:raise Unsupported('formula_dependency_not_computed')
            value=inputs.get(key)
            # A direct empty reference is numeric zero. Concatenation instead
            # coerces an empty referenced cell to empty text; preserve that
            # distinction until the caller's operation is known.
            return value
        if isinstance(n,Concat):
            parts=[];units=0
            for part in n.parts:
                value=_string(evaluate(part))
                if isinstance(value,ExcelError):return value
                units+=len(value.encode('utf-16-le'))//2
                if units>MAX_UTF16_UNITS:raise Unsupported('result_budget')
                parts.append(value)
            return ''.join(parts)
        raise Unsupported('unsupported_ast')
    result=evaluate(node)
    if result is None:result=0
    if isinstance(result,str) and len(result.encode('utf-16-le'))//2>MAX_UTF16_UNITS:raise Unsupported('result_budget')
    return result
